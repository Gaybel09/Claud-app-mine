import 'dart:ui';

import 'package:flame/components.dart';
import 'package:flutter/foundation.dart';

import 'combat.dart';
import 'fight_constants.dart';
import 'fighter_attributes.dart';
import 'fighter_input.dart';
import 'fighter_renderer.dart';
import 'fighter_rig.dart';
import 'fighter_state.dart';

/// Um lutador -- física cinemática (sem motor de física, ver decisão
/// registrada na conversa), máquina de estados, e o próprio desenho
/// procedural (ver fighter_renderer.dart). Tanto o jogador quanto a IA
/// controlam um Fighter da mesma forma: preenchendo [input] a cada frame
/// (ver PlayerController/AiController) -- o Fighter em si não sabe se quem
/// está do outro lado é humano ou IA.
class Fighter extends PositionComponent {
  Fighter({
    required this.attributes,
    required this.bodyColor,
    required this.accentColor,
    required Vector2 startPosition,
    required this.facing,
  }) : health = ValueNotifier(attributes.maxHealth),
       energy = ValueNotifier(attributes.maxEnergy.toDouble()) {
    position = startPosition;
    size = Vector2(FightConstants.fighterWidth, FightConstants.fighterHeight);
    anchor = Anchor.bottomCenter;
  }

  final FighterAttributes attributes;
  final Color bodyColor;
  final Color accentColor;

  final ValueNotifier<int> health;
  final ValueNotifier<double> energy;

  /// 1 = de frente pra direita, -1 = de frente pra esquerda. Atualizado de
  /// fora (ver FightWorld._updateFacing) enquanto o lutador não estiver
  /// travado num ataque/hit-stun -- não gira sozinho.
  int facing;

  /// Preenchido a cada frame por quem controla este lutador (toque do
  /// jogador ou AiController) -- ver FighterInputState.
  final FighterInputState input = FighterInputState();

  FighterState state = FighterState.idle;
  double stateTime = 0;
  double _idleClock = 0;
  final Vector2 velocity = Vector2.zero();

  AttackType? _activeAttack;
  bool _hasHitThisSwing = false;
  double _hitStunDuration = 0;
  bool _defeatedNotified = false;

  /// Chamado uma única vez, no frame em que a vida chega a zero.
  void Function()? onDefeated;

  FighterPose _pose = const FighterPose();

  bool get grounded => position.y >= FightConstants.groundY - 0.01;

  bool get isDefeated => state == FighterState.defeated;

  /// Retângulo de "corpo" -- sempre existe, é o que um golpe adversário
  /// precisa atingir pra acertar.
  Rect get hurtbox => Rect.fromLTWH(
    position.x - FightConstants.fighterWidth / 2,
    position.y - FightConstants.fighterHeight,
    FightConstants.fighterWidth,
    FightConstants.fighterHeight,
  );

  /// Retângulo do golpe em andamento -- só não-nulo durante a janela
  /// "active" do ataque (ver AttackSpec), e só uma vez por golpe (depois de
  /// markHitLanded(), volta a null até o próximo ataque).
  Rect? get activeHitbox {
    final type = _activeAttack;
    if (type == null || _hasHitThisSwing) return null;
    final spec = AttackSpec.of(type);
    if (stateTime < spec.startup || stateTime >= spec.startup + spec.active) {
      return null;
    }
    const hitboxHeight = 46.0;
    final top = position.y - FightConstants.fighterHeight * 0.62;
    final left = facing == 1 ? position.x : position.x - spec.range;
    return Rect.fromLTWH(left, top, spec.range, hitboxHeight);
  }

  AttackType? get activeAttackType => _activeAttack;

  void markHitLanded() => _hasHitThisSwing = true;

  /// Chamado por quem resolve o combate (FightWorld) quando este lutador
  /// É ATINGIDO por um golpe adversário -- nunca chamado pelo próprio
  /// Fighter.
  void applyHit({required int damage, required bool wasBlocked}) {
    if (isDefeated) return;
    health.value = (health.value - damage).clamp(0, attributes.maxHealth);
    if (health.value <= 0) {
      _enterState(FighterState.defeated);
      return;
    }
    _hitStunDuration = hitStunDuration(damage) * (wasBlocked ? 0.4 : 1.0);
    _enterState(FighterState.hitStun);
  }

  /// Vira pra encarar [opponentX] -- ignorado enquanto travado num
  /// ataque/hit-stun (não gira no meio de um golpe).
  void faceToward(double opponentX) {
    if (lockedStates.contains(state)) return;
    facing = opponentX >= position.x ? 1 : -1;
  }

  @override
  void update(double dt) {
    super.update(dt);
    _idleClock += dt;
    stateTime += dt;

    _advanceTimedStates();
    if (!isDefeated) {
      _consumeInput();
    }
    _applyPhysics(dt);
    _applyEnergy(dt);

    _pose = computePose(
      state: state,
      stateProgress: stateTime,
      grounded: grounded,
      idleClock: _idleClock,
    );

    if (isDefeated && !_defeatedNotified) {
      _defeatedNotified = true;
      onDefeated?.call();
    }
  }

  void _advanceTimedStates() {
    switch (state) {
      case FighterState.punch:
        if (stateTime >= AttackSpec.punch.total) _exitAttackToNeutral();
      case FighterState.kick:
        if (stateTime >= AttackSpec.kick.total) _exitAttackToNeutral();
      case FighterState.aerialPunch:
        if (stateTime >= AttackSpec.aerialPunch.total) _exitAttackToNeutral();
      case FighterState.hitStun:
        if (stateTime >= _hitStunDuration) _enterState(grounded ? FighterState.idle : FighterState.jump);
      case FighterState.idle:
      case FighterState.walk:
      case FighterState.jump:
      case FighterState.block:
      case FighterState.defeated:
        break;
    }
  }

  void _exitAttackToNeutral() {
    _activeAttack = null;
    _enterState(grounded ? FighterState.idle : FighterState.jump);
  }

  void _consumeInput() {
    if (lockedStates.contains(state)) return;

    if (input.jumpQueued) {
      input.consumeJump();
      if (grounded) {
        velocity.y = -attributes.jumpPower;
        _enterState(FighterState.jump);
        return;
      }
    }

    if (input.punchQueued) {
      input.consumePunch();
      if (!grounded) {
        _startAttack(AttackType.aerialPunch);
        return;
      } else if (energy.value >= FightConstants.punchEnergyCost) {
        _startAttack(AttackType.punch);
        return;
      }
    }

    if (input.kickQueued) {
      input.consumeKick();
      if (grounded && energy.value >= FightConstants.kickEnergyCost) {
        _startAttack(AttackType.kick);
        return;
      }
    }

    if (input.blockHeld && grounded && energy.value > FightConstants.blockBreakEnergyThreshold) {
      if (state != FighterState.block) _enterState(FighterState.block);
      return;
    }

    if (!grounded) {
      if (state != FighterState.jump) _enterState(FighterState.jump);
      return;
    }

    final moving = input.moveDir.abs() > 0.01;
    if (moving && state != FighterState.walk) {
      _enterState(FighterState.walk);
    } else if (!moving && state != FighterState.idle) {
      _enterState(FighterState.idle);
    }
  }

  void _startAttack(AttackType type) {
    final spec = AttackSpec.of(type);
    energy.value = (energy.value - spec.energyCost).clamp(0, attributes.maxEnergy.toDouble());
    _activeAttack = type;
    _hasHitThisSwing = false;
    final newState = switch (type) {
      AttackType.punch => FighterState.punch,
      AttackType.kick => FighterState.kick,
      AttackType.aerialPunch => FighterState.aerialPunch,
    };
    _enterState(newState);
  }

  void _enterState(FighterState newState) {
    state = newState;
    stateTime = 0;
  }

  void _applyPhysics(double dt) {
    velocity.x = lockedStates.contains(state) ? 0 : input.moveDir * attributes.speed;
    final halfWidth = FightConstants.fighterWidth / 2;
    position.x = (position.x + velocity.x * dt).clamp(halfWidth, FightConstants.arenaWidth - halfWidth);

    velocity.y += FightConstants.gravity * dt;
    position.y += velocity.y * dt;
    if (position.y > FightConstants.groundY) {
      position.y = FightConstants.groundY;
      velocity.y = 0;
    }
  }

  void _applyEnergy(double dt) {
    if (state == FighterState.block) {
      energy.value = (energy.value - FightConstants.blockEnergyDrainPerSecond * dt).clamp(
        0,
        attributes.maxEnergy.toDouble(),
      );
      if (energy.value <= 0) {
        _enterState(grounded ? FighterState.idle : FighterState.jump);
      }
    } else {
      energy.value = (energy.value + FightConstants.energyRegenPerSecond * dt).clamp(
        0,
        attributes.maxEnergy.toDouble(),
      );
    }
  }

  @override
  void render(Canvas canvas) {
    renderFighterRig(
      canvas,
      pose: _pose,
      width: size.x,
      height: size.y,
      facing: facing,
      bodyColor: bodyColor,
      accentColor: accentColor,
      opacity: isDefeated ? 0.65 : 1.0,
    );
  }
}

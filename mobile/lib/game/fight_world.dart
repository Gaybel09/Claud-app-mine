import 'dart:ui';

import 'package:flame/components.dart';

import 'ai_controller.dart';
import 'combat.dart';
import 'fight_constants.dart';
import 'fighter.dart';
import 'fighter_attributes.dart';
import 'fighter_state.dart';

class _Ground extends PositionComponent {
  _Ground()
    : super(
        position: Vector2(0, FightConstants.groundY),
        size: Vector2(FightConstants.arenaWidth, FightConstants.arenaHeight - FightConstants.groundY),
      );

  static final _fillPaint = Paint()..color = const Color(0xFF15151F);
  static final _linePaint = Paint()
    ..color = const Color(0xFF00E5FF)
    ..strokeWidth = 3;

  @override
  void render(Canvas canvas) {
    canvas.drawRect(Rect.fromLTWH(0, 0, size.x, size.y), _fillPaint);
    canvas.drawLine(const Offset(0, 0), Offset(size.x, 0), _linePaint);
  }
}

/// Mundo do combate: os dois lutadores, o chão, a IA do oponente, e a
/// resolução de combate (hitbox x hurtbox) a cada frame. Não sabe nada de
/// câmera (isso é do FightGame) nem de controles touch (isso é da tela) --
/// só recebe o [FighterInputState] do jogador já preenchido de fora.
class FightWorld extends World {
  late final Fighter player;
  late final Fighter opponent;
  late final AiController _aiController;

  /// Chamado uma única vez, [FightConstants.matchEndDelaySeconds] depois da
  /// vida de um dos dois chegar a zero -- true se o jogador venceu.
  void Function(bool playerWon)? onMatchEnd;

  bool _resultsPending = false;
  bool _matchEnded = false;
  bool _playerWon = false;
  double _endDelayRemaining = 0;

  @override
  Future<void> onLoad() async {
    await super.onLoad();

    add(_Ground());

    player = Fighter(
      attributes: FighterAttributes.balanced,
      bodyColor: const Color(0xFF00E5FF),
      accentColor: const Color(0xFFF5F5FF),
      startPosition: Vector2(FightConstants.arenaWidth * 0.35, FightConstants.groundY),
      facing: 1,
    )..onDefeated = () => _beginEndSequence(playerWon: false);

    opponent = Fighter(
      attributes: FighterAttributes.balanced,
      bodyColor: const Color(0xFFE026FF),
      accentColor: const Color(0xFFF5F5FF),
      startPosition: Vector2(FightConstants.arenaWidth * 0.65, FightConstants.groundY),
      facing: -1,
    )..onDefeated = () => _beginEndSequence(playerWon: true);

    _aiController = AiController(fighter: opponent, opponent: player);

    addAll([player, opponent]);
  }

  @override
  void update(double dt) {
    if (!_matchEnded) {
      _aiController.update(dt);
    }
  }

  /// Resolução de combate precisa rodar DEPOIS que os dois Fighters já
  /// tiverem processado a física/máquina de estados do próprio frame --
  /// mas [update] de um componente pai roda ANTES de [update] dos filhos
  /// (ver Component.updateTree em flame/component.dart: `update(dt)` do
  /// próprio nó primeiro, só depois percorre os filhos). Se a checagem de
  /// hitbox ficasse dentro de [update] (como estava antes), ela sempre
  /// enxergaria o stateTime/posição de UM FRAME ATRÁS dos lutadores --
  /// golpes ainda acertavam na prática (a janela "active" dura vários
  /// frames), mas com um atraso de 1 frame que não faz sentido e que
  /// testes mais precisos (que param exatamente na borda da janela)
  /// expunham como falha. Por isso a resolução pós-física mora aqui, em
  /// updateTree, que roda depois de super.updateTree(dt) já ter
  /// atualizado os filhos.
  @override
  void updateTree(double dt) {
    super.updateTree(dt);
    if (_matchEnded) return;

    _preventOverlap();
    _updateFacing();
    _resolveCombat();

    if (_resultsPending) {
      _endDelayRemaining -= dt;
      if (_endDelayRemaining <= 0) {
        _matchEnded = true;
        onMatchEnd?.call(_playerWon);
      }
    }
  }

  /// Impede que os dois lutadores se atravessem -- se ficarem mais perto
  /// que [FightConstants.minFighterSeparation], empurra os dois igualmente
  /// pra fora até respeitar a distância mínima (e reclampa nas bordas da
  /// arena, já que o empurrão pode jogar alguém pra fora perto de uma
  /// parede).
  void _preventOverlap() {
    final dx = opponent.position.x - player.position.x;
    final distance = dx.abs();
    if (distance >= FightConstants.minFighterSeparation) return;

    final push = (FightConstants.minFighterSeparation - distance) / 2;
    // dx.sign é 0 se os dois estiverem EXATAMENTE na mesma posição (só em
    // teoria) -- escolhe uma direção arbitrária (mas consistente) nesse
    // caso, em vez de ficar preso sem separar.
    final sign = distance == 0 ? 1.0 : dx.sign;
    final halfWidth = FightConstants.fighterWidth / 2;
    player.position.x = (player.position.x - push * sign).clamp(
      halfWidth,
      FightConstants.arenaWidth - halfWidth,
    );
    opponent.position.x = (opponent.position.x + push * sign).clamp(
      halfWidth,
      FightConstants.arenaWidth - halfWidth,
    );
  }

  void _updateFacing() {
    player.faceToward(opponent.position.x);
    opponent.faceToward(player.position.x);
  }

  void _resolveCombat() {
    _checkAttack(attacker: player, defender: opponent);
    _checkAttack(attacker: opponent, defender: player);
  }

  void _checkAttack({required Fighter attacker, required Fighter defender}) {
    final hitbox = attacker.activeHitbox;
    final attackType = attacker.activeAttackType;
    if (hitbox == null || attackType == null) return;
    if (!hitbox.overlaps(defender.hurtbox)) return;

    final blocked = defender.state == FighterState.block && _isAttackFromFront(attacker: attacker, defender: defender);
    final damage = resolveDamage(
      type: attackType,
      attackerAttack: attacker.attributes.attack,
      defenderDefense: defender.attributes.defense,
      blocked: blocked,
    );
    defender.applyHit(damage: damage, wasBlocked: blocked);
    attacker.markHitLanded();
  }

  /// A defesa só bloqueia golpes vindo de quem o defensor está encarando --
  /// um golpe "pelas costas" (não deveria acontecer com a IA atual, que
  /// sempre encara o jogador, mas é uma checagem barata e correta de ter).
  bool _isAttackFromFront({required Fighter attacker, required Fighter defender}) {
    return defender.facing == 1
        ? attacker.position.x >= defender.position.x
        : attacker.position.x <= defender.position.x;
  }

  void _beginEndSequence({required bool playerWon}) {
    if (_resultsPending || _matchEnded) return;
    _resultsPending = true;
    _playerWon = playerWon;
    _endDelayRemaining = FightConstants.matchEndDelaySeconds;
  }
}

import 'package:cubemine_pix/game/fight_constants.dart';
import 'package:cubemine_pix/game/fighter.dart';
import 'package:cubemine_pix/game/fighter_attributes.dart';
import 'package:cubemine_pix/game/fighter_state.dart';
import 'package:flame/components.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Fighter não precisa estar montado numa árvore de componentes pra sua
/// própria lógica de física/máquina de estados funcionar -- update() só lê
/// e escreve os próprios campos. Testar direto, sem FlameGame/World, deixa
/// esses testes rápidos e focados só no comportamento do lutador em si
/// (a integração com FightWorld -- combate entre dois lutadores de
/// verdade, câmera, etc. -- é coberta em fight_world_test.dart).
Fighter _makeFighter({double x = 500, int facing = 1}) {
  return Fighter(
    attributes: FighterAttributes.balanced,
    bodyColor: Colors.cyan,
    accentColor: Colors.white,
    startPosition: Vector2(x, FightConstants.groundY),
    facing: facing,
  );
}

void main() {
  group('Fighter movement', () {
    test('walks in the direction of input.moveDir at attributes.speed', () {
      final fighter = _makeFighter(x: 500);
      fighter.input.moveDir = 1;
      const dt = 1 / 60;
      final startX = fighter.position.x;
      for (var i = 0; i < 60; i++) {
        fighter.update(dt);
      }
      // ~1s de movimento a `speed` unidades/s -- não exatamente igual por
      // causa do primeiro frame ainda estar em `idle` antes de virar
      // `walk`, mas deve ter avançado quase toda a distância esperada.
      expect(fighter.position.x - startX, closeTo(FightConstants.baseSpeed, FightConstants.baseSpeed * 0.05));
      expect(fighter.state, FighterState.walk);
    });

    test('stays within the arena bounds even holding movement past the edge', () {
      final fighter = _makeFighter(x: 10);
      fighter.input.moveDir = -1;
      for (var i = 0; i < 300; i++) {
        fighter.update(1 / 60);
      }
      expect(fighter.position.x, greaterThanOrEqualTo(FightConstants.fighterWidth / 2));
    });

    test('jumping applies upward velocity then gravity brings it back to the ground', () {
      final fighter = _makeFighter();
      fighter.input.jumpQueued = true;
      fighter.update(1 / 60);

      expect(fighter.grounded, isFalse);
      expect(fighter.state, FighterState.jump);

      // Roda tempo suficiente pra completar o arco do pulo (jumpPower /
      // gravity * ~2, com folga).
      final airTime = (2 * FightConstants.baseJumpPower / FightConstants.gravity) + 1.0;
      var elapsed = 0.0;
      while (elapsed < airTime) {
        fighter.update(1 / 60);
        elapsed += 1 / 60;
      }
      expect(fighter.grounded, isTrue);
      expect(fighter.position.y, FightConstants.groundY);
    });

    test('cannot jump again while already airborne', () {
      final fighter = _makeFighter();
      fighter.input.jumpQueued = true;
      fighter.update(1 / 60);
      final velocityAfterFirstJump = fighter.velocity.y;

      fighter.input.jumpQueued = true;
      fighter.update(1 / 60);
      // Só a gravidade deveria ter mexido em velocity.y entre os dois
      // frames -- nunca outro impulso de -jumpPower somado por cima.
      expect(fighter.velocity.y, greaterThan(velocityAfterFirstJump));
    });
  });

  group('Fighter attacks', () {
    test('punch consumes energy and enters the punch state', () {
      final fighter = _makeFighter();
      final energyBefore = fighter.energy.value;
      fighter.input.punchQueued = true;
      fighter.update(1 / 60);

      expect(fighter.state, FighterState.punch);
      // Não exatamente energyBefore - custo: a mesma chamada a update()
      // também aplica a regeneração passiva de energia (1 frame, ver
      // Fighter._applyEnergy -- só bloquear DRENA, todo o resto regenera).
      expect(
        fighter.energy.value,
        closeTo(energyBefore - FightConstants.punchEnergyCost, FightConstants.energyRegenPerSecond * (1 / 60) + 0.01),
      );
      expect(fighter.energy.value, lessThan(energyBefore));
    });

    test('punching while airborne triggers an aerial punch, not a grounded punch', () {
      final fighter = _makeFighter();
      fighter.input.jumpQueued = true;
      fighter.update(1 / 60);
      expect(fighter.grounded, isFalse);

      fighter.input.punchQueued = true;
      fighter.update(1 / 60);
      expect(fighter.state, FighterState.aerialPunch);
    });

    test('kick does nothing while airborne (not a defined move)', () {
      final fighter = _makeFighter();
      fighter.input.jumpQueued = true;
      fighter.update(1 / 60);

      fighter.input.kickQueued = true;
      fighter.update(1 / 60);
      expect(fighter.state, isNot(FighterState.kick));
    });

    test('cannot attack again while a punch is still active (locked state)', () {
      final fighter = _makeFighter();
      fighter.input.punchQueued = true;
      fighter.update(1 / 60);
      final energyAfterFirstPunch = fighter.energy.value;

      fighter.input.kickQueued = true;
      fighter.update(1 / 60);
      // Ainda travado no soco -- o chute enfileirado não devia ter sido
      // consumido nem gastado energia.
      expect(fighter.state, FighterState.punch);
      expect(fighter.energy.value, greaterThanOrEqualTo(energyAfterFirstPunch));
    });

    test('refuses to attack without enough energy', () {
      final fighter = _makeFighter();
      fighter.energy.value = 5; // abaixo do custo de qualquer ataque
      fighter.input.kickQueued = true;
      fighter.update(1 / 60);
      expect(fighter.state, isNot(FighterState.kick));
    });

    test('activeHitbox is null outside the attack active window, non-null inside it', () {
      final fighter = _makeFighter();
      fighter.input.punchQueued = true;
      fighter.update(1 / 60); // entra no soco, ainda em startup

      expect(fighter.activeHitbox, isNull);

      final startupPlusEpsilon = FightConstants.punchStartup + 0.01;
      var elapsed = 1 / 60;
      while (elapsed < startupPlusEpsilon) {
        fighter.update(1 / 60);
        elapsed += 1 / 60;
      }
      expect(fighter.activeHitbox, isNotNull);
    });

    test('markHitLanded prevents the same swing from hitting twice', () {
      final fighter = _makeFighter();
      fighter.input.punchQueued = true;
      fighter.update(1 / 60);
      var elapsed = 1 / 60;
      while (elapsed < FightConstants.punchStartup + 0.01) {
        fighter.update(1 / 60);
        elapsed += 1 / 60;
      }
      expect(fighter.activeHitbox, isNotNull);
      fighter.markHitLanded();
      expect(fighter.activeHitbox, isNull);
    });
  });

  group('Fighter block', () {
    test('blocking drains energy over time', () {
      final fighter = _makeFighter();
      fighter.input.blockHeld = true;
      final before = fighter.energy.value;
      for (var i = 0; i < 30; i++) {
        fighter.update(1 / 60);
      }
      expect(fighter.energy.value, lessThan(before));
      expect(fighter.state, FighterState.block);
    });

    test('guard breaks (drops) once energy is depleted', () {
      final fighter = _makeFighter();
      fighter.input.blockHeld = true;
      // 100 energia / (8/s de dreno * 1/60 por frame) = 750 frames pra
      // zerar -- roda bem além disso pra garantir que já quebrou.
      for (var i = 0; i < 800; i++) {
        fighter.update(1 / 60);
      }
      expect(fighter.state, isNot(FighterState.block));
    });
  });

  group('Fighter applyHit', () {
    test('reduces health and enters hitStun when damage does not kill', () {
      final fighter = _makeFighter();
      fighter.applyHit(damage: 10, wasBlocked: false);
      expect(fighter.health.value, FightConstants.baseHealth - 10);
      expect(fighter.state, FighterState.hitStun);
      expect(fighter.isDefeated, isFalse);
    });

    test('enters defeated state and clamps health at 0 when damage exceeds remaining health', () {
      final fighter = _makeFighter();
      fighter.applyHit(damage: FightConstants.baseHealth + 50, wasBlocked: false);
      expect(fighter.health.value, 0);
      expect(fighter.isDefeated, isTrue);
      expect(fighter.state, FighterState.defeated);
    });

    test('does nothing once already defeated (no negative health, no state change)', () {
      final fighter = _makeFighter();
      fighter.applyHit(damage: FightConstants.baseHealth + 50, wasBlocked: false);
      fighter.applyHit(damage: 999, wasBlocked: false);
      expect(fighter.health.value, 0);
      expect(fighter.state, FighterState.defeated);
    });

    test('a defeated fighter no longer responds to input', () {
      final fighter = _makeFighter();
      fighter.applyHit(damage: FightConstants.baseHealth + 50, wasBlocked: false);

      fighter.input.moveDir = 1;
      fighter.input.punchQueued = true;
      final xBefore = fighter.position.x;
      fighter.update(1 / 60);

      expect(fighter.state, FighterState.defeated);
      expect(fighter.position.x, xBefore);
    });

    test('calls onDefeated exactly once', () {
      final fighter = _makeFighter();
      var callCount = 0;
      fighter.onDefeated = () => callCount++;

      fighter.applyHit(damage: FightConstants.baseHealth + 50, wasBlocked: false);
      fighter.update(1 / 60);
      fighter.update(1 / 60);
      fighter.update(1 / 60);

      expect(callCount, 1);
    });
  });

  group('Fighter facing', () {
    test('faces toward the opponent when free to act', () {
      final fighter = _makeFighter(x: 500, facing: 1);
      fighter.faceToward(100); // oponente à esquerda
      expect(fighter.facing, -1);
      fighter.faceToward(900); // oponente à direita
      expect(fighter.facing, 1);
    });

    test('does not turn around mid-attack', () {
      final fighter = _makeFighter(x: 500, facing: 1);
      fighter.input.punchQueued = true;
      fighter.update(1 / 60);
      expect(fighter.state, FighterState.punch);

      fighter.faceToward(100); // tentaria virar pra esquerda
      expect(fighter.facing, 1); // mas continua travado olhando pra direita
    });
  });
}

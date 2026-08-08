import 'package:cubemine_pix/game/combat.dart';
import 'package:cubemine_pix/game/fight_constants.dart';
import 'package:cubemine_pix/game/fight_game.dart';
import 'package:cubemine_pix/game/fighter_state.dart';
import 'package:flame_test/flame_test.dart';
import 'package:flutter_test/flutter_test.dart';

/// Testes de integração de verdade (dois Fighters + FightWorld + câmera),
/// via flame_test -- monta um FightGame real (mesma sequência de
/// load()+mount()+update(0) que GameWidget usa em produção) sem precisar
/// de um navegador nem de um widget host. Complementa fighter_test.dart
/// (que testa UM lutador isolado) cobrindo o que só existe quando os DOIS
/// interagem: combate, sobreposição, fim de partida. Cada bloco
/// testWithGame recebe sua PRÓPRIA instância nova de FightGame -- nunca
/// precisa criar um segundo jogo manualmente dentro do corpo do teste.
void main() {
  group('FightWorld setup', () {
    testWithGame<FightGame>(
      'creates two fighters on opposite sides, facing each other',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        await game.ready();

        expect(game.player.position.x, lessThan(game.opponent.position.x));
        expect(game.player.facing, 1);
        expect(game.opponent.facing, -1);
        expect(game.player.health.value, FightConstants.baseHealth);
        expect(game.opponent.health.value, FightConstants.baseHealth);
      },
    );
  });

  group('FightWorld combat resolution', () {
    testWithGame<FightGame>(
      'a landed punch damages the defender and does not damage the attacker',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        await game.ready();
        final player = game.player;
        final opponent = game.opponent;

        // Cola os dois bem perto (dentro do alcance de soco) sem passar
        // pela física de movimento -- o teste quer isolar "o soco acerta
        // e causa dano", não uma troca de golpes de verdade. Reforça
        // posição de AMBOS + zera a energia do oponente A CADA frame do
        // laço, antes de cada game.update():
        // - Posição: a IA (Random real, sem seed) já tomou sua primeira
        //   decisão durante game.ready() usando as posições ORIGINAIS
        //   (bem distantes) e, como o cooldown dela ainda não venceu,
        //   reaplica esse moveDir antigo -- sem reforçar as duas
        //   posições, elas derivam (inclusive _preventOverlap empurra o
        //   JOGADOR pra longe se o gap escolhido for menor que
        //   minFighterSeparation).
        // - Energia zerada: sem isso, o oponente (dentro do alcance de
        //   ataque da própria IA) contra-ataca e pode interromper o soco
        //   do jogador com hitStun ANTES dele ficar ativo -- o teste quer
        //   isolar "o golpe do jogador conecta", não uma troca dos dois
        //   lados.
        const opponentOffsetX = 80.0; // > minFighterSeparation, dentro de punchRange
        void pinPositions() {
          player.position.x = 1000;
          opponent.position.x = 1000 + opponentOffsetX;
          opponent.energy.value = 0;
        }

        pinPositions();
        game.update(0); // recalcula facing pros novos lugares antes de atacar

        player.input.punchQueued = true;
        var elapsed = 0.0;
        final untilActive = FightConstants.punchStartup + 0.01;
        while (elapsed < untilActive) {
          pinPositions();
          game.update(1 / 60);
          elapsed += 1 / 60;
        }

        expect(opponent.health.value, lessThan(FightConstants.baseHealth));
        expect(player.health.value, FightConstants.baseHealth);
      },
    );

    testWithGame<FightGame>(
      'a blocked punch deals less damage than an unblocked one would',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        await game.ready();
        final player = game.player;
        final opponent = game.opponent;
        const offsetX = 80.0;
        void pinPositions() {
          player.position.x = 1000;
          opponent.position.x = 1000 + offsetX;
        }

        pinPositions();
        game.update(0);

        // Papéis invertidos de propósito em relação ao teste acima: aqui
        // é o OPONENTE que ataca e o JOGADOR que bloqueia -- não o
        // contrário. `opponent.input.blockHeld` é um dos dois campos que
        // AiController._applyMovementAndBlock reafirma TODO frame por
        // cima do que o teste setar (a decisão real da IA, não a nossa),
        // então forçar o oponente a bloquear nunca "gruda". Já
        // `player.input` não tem nenhum controller mexendo -- só o
        // teste. `punchQueued`/`kickQueued` são a exceção nos dois casos
        // (a IA só os liga no instante exato de uma nova decisão, nunca
        // reafirma), por isso `opponent.input.punchQueued` abaixo
        // funciona mesmo o oponente sendo controlado pela IA.
        player.input.blockHeld = true;
        game.update(1 / 60); // jogador entra em `block` antes do soco chegar

        opponent.input.punchQueued = true;
        var elapsed = 0.0;
        final untilActive = FightConstants.punchStartup + 0.02;
        while (elapsed < untilActive) {
          pinPositions();
          player.input.blockHeld = true;
          game.update(1 / 60);
          elapsed += 1 / 60;
        }

        final blockedDamage = FightConstants.baseHealth - player.health.value;
        final unblockedDamage = resolveDamage(
          type: AttackType.punch,
          attackerAttack: opponent.attributes.attack,
          defenderDefense: player.attributes.defense,
          blocked: false,
        );

        expect(blockedDamage, greaterThan(0)); // guarda nunca zera o dano de todo
        expect(blockedDamage, lessThan(unblockedDamage));
      },
    );

    testWithGame<FightGame>(
      'fighters cannot walk through each other past the minimum separation',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        await game.ready();
        game.player.position.x = 1000;
        game.opponent.position.x = 1000 + FightConstants.minFighterSeparation - 1;

        game.update(1 / 60);

        final distance = (game.opponent.position.x - game.player.position.x).abs();
        expect(distance, greaterThanOrEqualTo(FightConstants.minFighterSeparation - 0.01));
        // A ordem esquerda/direita não deveria ter trocado numa única
        // resolução de sobreposição.
        expect(game.player.position.x, lessThan(game.opponent.position.x));
      },
    );
  });

  group('FightWorld match end', () {
    testWithGame<FightGame>(
      'declares the player the winner when the opponent is defeated, after the end delay',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        bool? playerWon;
        await game.ready();
        game.world.onMatchEnd = (won) => playerWon = won;

        game.opponent.applyHit(damage: FightConstants.baseHealth + 999, wasBlocked: false);
        expect(game.opponent.isDefeated, isTrue);
        expect(playerWon, isNull); // ainda não -- espera o delay de fim de partida

        var elapsed = 0.0;
        while (elapsed < FightConstants.matchEndDelaySeconds + 0.1) {
          game.update(1 / 60);
          elapsed += 1 / 60;
        }

        expect(playerWon, isTrue);
      },
    );

    testWithGame<FightGame>(
      'declares the opponent the winner when the player is defeated',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        bool? playerWon;
        await game.ready();
        game.world.onMatchEnd = (won) => playerWon = won;

        game.player.applyHit(damage: FightConstants.baseHealth + 999, wasBlocked: false);

        var elapsed = 0.0;
        while (elapsed < FightConstants.matchEndDelaySeconds + 0.1) {
          game.update(1 / 60);
          elapsed += 1 / 60;
        }

        expect(playerWon, isFalse);
      },
    );

    testWithGame<FightGame>(
      'never reports a winner while the match is still ongoing',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        bool? playerWon;
        await game.ready();
        game.world.onMatchEnd = (won) => playerWon = won;

        for (var i = 0; i < 120; i++) {
          game.update(1 / 60);
        }

        expect(playerWon, isNull);
        expect(game.player.state, isNot(FighterState.defeated));
        expect(game.opponent.state, isNot(FighterState.defeated));
      },
    );
  });

  group('FightWorld camera', () {
    testWithGame<FightGame>(
      'keeps the viewfinder roughly centered between both fighters',
      () => FightGame(onMatchEnd: (_) {}),
      (game) async {
        await game.ready();
        game.update(1 / 60);

        final expectedMidX = (game.player.position.x + game.opponent.position.x) / 2;
        expect(game.camera.viewfinder.position.x, closeTo(expectedMidX, 1.0));
      },
    );
  });
}

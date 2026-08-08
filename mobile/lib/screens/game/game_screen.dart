import 'package:flame/game.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../game/fight_game.dart';
import '../../game/hud_overlay.dart';
import '../../game/result_overlay.dart';
import '../../game/touch_controls.dart';

/// Tela do minigame de luta (Fase 1) -- trava a orientação em paisagem
/// SÓ enquanto esta tela está montada (restaura em dispose). Funciona
/// porque HomeShell troca de aba substituindo o widget inteiro (não usa
/// IndexedStack), então sair da aba "Jogar" sempre desmonta esta tela de
/// verdade, disparando o dispose -- ver mobile/lib/screens/home/home_shell.dart.
class GameScreen extends StatefulWidget {
  const GameScreen({super.key});

  @override
  State<GameScreen> createState() => _GameScreenState();
}

class _GameScreenState extends State<GameScreen> {
  int _matchId = 0;
  late FightGame _game;
  bool? _playerWon;

  @override
  void initState() {
    super.initState();
    SystemChrome.setPreferredOrientations([DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]);
    _game = FightGame(onMatchEnd: _handleMatchEnd);
  }

  @override
  void dispose() {
    SystemChrome.setPreferredOrientations(DeviceOrientation.values);
    super.dispose();
  }

  void _handleMatchEnd(bool playerWon) {
    if (!mounted) return;
    setState(() => _playerWon = playerWon);
  }

  void _rematch() {
    setState(() {
      _matchId++;
      _playerWon = null;
      _game = FightGame(onMatchEnd: _handleMatchEnd);
    });
  }

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.black,
      child: FutureBuilder<void>(
        // world.loaded só resolve depois de FightWorld.onLoad() rodar --
        // antes disso, _game.player/_game.opponent ainda não existem
        // (Fighter é `late final`, setado dentro do onLoad). HUD/controles
        // só entram na árvore depois que isso resolve, pra nunca ler esses
        // getters cedo demais.
        key: ValueKey(_matchId),
        future: _game.world.loaded,
        builder: (context, snapshot) {
          final ready = snapshot.connectionState == ConnectionState.done;
          return Stack(
            children: [
              Positioned.fill(child: GameWidget(game: _game)),
              if (ready) ...[
                Positioned.fill(child: FightHud(player: _game.player, opponent: _game.opponent)),
                if (_playerWon == null)
                  Positioned.fill(
                    child: TouchControls(
                      onMoveDirChanged: (dir) => _game.player.input.moveDir = dir,
                      onBlockChanged: (held) => _game.player.input.blockHeld = held,
                      onJump: () => _game.player.input.jumpQueued = true,
                      onPunch: () => _game.player.input.punchQueued = true,
                      onKick: () => _game.player.input.kickQueued = true,
                    ),
                  )
                else
                  Positioned.fill(
                    child: FightResultOverlay(
                      playerWon: _playerWon!,
                      onRematch: _rematch,
                      onExit: () => Navigator.of(context).maybePop(),
                    ),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

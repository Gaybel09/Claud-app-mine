import 'dart:ui';

import 'package:flame/game.dart';

import 'fight_constants.dart';
import 'fight_world.dart';
import 'fighter.dart';

/// FlameGame do minigame de luta (Fase 1) -- dono da câmera lateral (segue
/// o ponto médio dos dois lutadores, com zoom dinâmico pra manter os dois
/// visíveis mesmo se afastarem). Toda a regra de jogo em si mora em
/// [FightWorld]; este componente só cuida de câmera + fundo.
class FightGame extends FlameGame<FightWorld> {
  FightGame({required this.onMatchEnd}) : super(world: FightWorld());

  final void Function(bool playerWon) onMatchEnd;

  Fighter get player => world.player;
  Fighter get opponent => world.opponent;

  static const _minZoom = 0.65;
  static const _maxZoom = 1.25;
  static const _zoomNearDistance = 220.0;
  static const _zoomFarDistance = 900.0;

  // world.player/world.opponent só existem depois de FightWorld.onLoad()
  // terminar -- e isso só acontece DEPOIS que FightGame.onLoad() retorna
  // (GameWidgetState monta os filhos do jogo -- `game.mount()` -- só
  // depois de `await game.load()` completar, ver flame/src/game/
  // game_widget/game_widget.dart:loaderFuture). Um `await world.loaded`
  // AQUI DENTRO de onLoad já causou um deadlock real (o load nunca
  // termina, porque está esperando algo que só acontece depois dele
  // terminar) -- por isso esta classe nunca lê world.player/opponent no
  // onLoad, só depois, em _updateCamera, guardado por world.isLoaded
  // (checagem síncrona, sem esperar future nenhum).
  bool _cameraInitialized = false;

  @override
  Color backgroundColor() => const Color(0xFF0B0B14);

  @override
  Future<void> onLoad() async {
    await super.onLoad();
    world.onMatchEnd = onMatchEnd;
    camera.viewfinder.zoom = _maxZoom;
  }

  @override
  void update(double dt) {
    super.update(dt);
    if (world.isLoaded) {
      _updateCamera();
    }
  }

  void _updateCamera() {
    if (size.x <= 0 || size.y <= 0) return;

    final midX = (world.player.position.x + world.opponent.position.x) / 2;
    final distance = (world.player.position.x - world.opponent.position.x).abs();

    final viewfinder = camera.viewfinder;
    final targetZoom = _zoomForDistance(distance);
    final visibleHalfWidth = (size.x / 2) / viewfinder.zoom;
    final clampedX = midX.clamp(visibleHalfWidth, FightConstants.arenaWidth - visibleHalfWidth);
    const targetY = FightConstants.groundY - FightConstants.fighterHeight * 0.55;

    if (!_cameraInitialized) {
      // Primeira vez que o mundo está pronto -- posiciona a câmera direto
      // no alvo (sem lerp), senão ela "nasceria" no canto (0,0) padrão do
      // CameraComponent e se arrastaria visivelmente até o lugar certo no
      // primeiro segundo de jogo.
      viewfinder.zoom = targetZoom;
      viewfinder.position = Vector2(clampedX, targetY);
      _cameraInitialized = true;
      return;
    }

    viewfinder.zoom = _lerp(viewfinder.zoom, targetZoom, 0.06);
    viewfinder.position = Vector2(
      _lerp(viewfinder.position.x, clampedX, 0.12),
      _lerp(viewfinder.position.y, targetY, 0.12),
    );
  }

  double _zoomForDistance(double distance) {
    final t = ((distance - _zoomNearDistance) / (_zoomFarDistance - _zoomNearDistance)).clamp(0.0, 1.0);
    return _maxZoom + (_minZoom - _maxZoom) * t;
  }
}

double _lerp(double a, double b, double t) => a + (b - a) * t;

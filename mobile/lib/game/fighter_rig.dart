import 'dart:math' as math;

import 'fighter_state.dart';

/// Pose procedural de um lutador num instante -- só números (ângulos em
/// radianos, deslocamentos em unidades locais), sem nada de Canvas/Flame
/// aqui, então dá pra testar a matemática isolada do desenho de verdade
/// (ver FighterRig.render em fighter.dart pra quem consome isto).
///
/// Convenção: ângulo 0 = membro pendurado reto pra baixo (braço) ou
/// esticado reto pra baixo (perna); ângulos positivos giram a ponta do
/// membro PRA FRENTE (sentido em que o lutador está de frente).
class FighterPose {
  const FighterPose({
    this.torsoAngle = 0,
    this.headBobY = 0,
    this.frontArmAngle = 0.15,
    this.backArmAngle = -0.1,
    this.frontLegAngle = 0,
    this.backLegAngle = 0,
    this.crouch = 0,
  });

  /// Inclinação do tronco+cabeça (positivo = inclina pra frente).
  final double torsoAngle;

  /// Deslocamento vertical extra da cabeça (idle "respirando").
  final double headBobY;

  final double frontArmAngle;
  final double backArmAngle;
  final double frontLegAngle;
  final double backLegAngle;

  /// 0 (em pé) .. 1 (agachado) -- usado por block/hitStun/defeated pra
  /// abaixar o centro de massa visualmente.
  final double crouch;

  static FighterPose lerp(FighterPose a, FighterPose b, double t) {
    return FighterPose(
      torsoAngle: _lerpD(a.torsoAngle, b.torsoAngle, t),
      headBobY: _lerpD(a.headBobY, b.headBobY, t),
      frontArmAngle: _lerpD(a.frontArmAngle, b.frontArmAngle, t),
      backArmAngle: _lerpD(a.backArmAngle, b.backArmAngle, t),
      frontLegAngle: _lerpD(a.frontLegAngle, b.frontLegAngle, t),
      backLegAngle: _lerpD(a.backLegAngle, b.backLegAngle, t),
      crouch: _lerpD(a.crouch, b.crouch, t),
    );
  }
}

double _lerpD(double a, double b, double t) => a + (b - a) * t;

/// Calcula a pose de um estado num dado instante -- pura função de
/// (estado, progresso 0..1 dentro do estado, se está no ar, relógio de
/// idle pro balanço) pra uma [FighterPose]. Nenhum estado aqui muta nada;
/// Fighter.update() é quem decide QUANDO trocar de estado.
FighterPose computePose({
  required FighterState state,
  required double stateProgress,
  required bool grounded,
  required double idleClock,
}) {
  switch (state) {
    case FighterState.idle:
      final sway = math.sin(idleClock * 2.2) * 0.05;
      return FighterPose(
        headBobY: math.sin(idleClock * 2.2) * 2,
        frontArmAngle: 0.12 + sway,
        backArmAngle: -0.08 - sway,
        frontLegAngle: 0,
        backLegAngle: 0,
      );

    case FighterState.walk:
      final stride = math.sin(idleClock * 9) * 0.5;
      return FighterPose(
        torsoAngle: 0.05,
        frontArmAngle: -stride * 0.4,
        backArmAngle: stride * 0.4,
        frontLegAngle: stride,
        backLegAngle: -stride,
      );

    case FighterState.jump:
      return const FighterPose(
        torsoAngle: -0.05,
        frontArmAngle: -0.3,
        backArmAngle: 0.3,
        frontLegAngle: -0.35,
        backLegAngle: 0.5,
      );

    case FighterState.punch:
      // startup (0..0.3): puxa o braço; active/recovery (0.3..1): estica.
      final extend = stateProgress < 0.3 ? -0.3 * (stateProgress / 0.3) : math.min(1.6, 1.6 * ((stateProgress - 0.3) / 0.3));
      return FighterPose(torsoAngle: 0.18, frontArmAngle: extend, backArmAngle: -0.2, frontLegAngle: 0.1, backLegAngle: -0.05);

    case FighterState.aerialPunch:
      final extend = math.min(1.5, stateProgress * 3);
      return FighterPose(
        torsoAngle: 0.1,
        frontArmAngle: extend,
        backArmAngle: -0.2,
        frontLegAngle: -0.2,
        backLegAngle: 0.35,
      );

    case FighterState.kick:
      final extend = stateProgress < 0.4 ? 0.6 * (stateProgress / 0.4) : math.min(1.7, 1.7 * ((stateProgress - 0.4) / 0.3));
      return FighterPose(
        torsoAngle: -0.15,
        frontArmAngle: 0.4,
        backArmAngle: -0.3,
        frontLegAngle: extend,
        backLegAngle: -0.15,
        crouch: 0.1,
      );

    case FighterState.block:
      return const FighterPose(
        torsoAngle: -0.08,
        frontArmAngle: -1.1,
        backArmAngle: -0.9,
        frontLegAngle: 0.1,
        backLegAngle: -0.1,
        crouch: 0.15,
      );

    case FighterState.hitStun:
      return const FighterPose(
        torsoAngle: -0.3,
        frontArmAngle: -0.5,
        backArmAngle: 0.6,
        frontLegAngle: -0.1,
        backLegAngle: 0.2,
        crouch: 0.1,
      );

    case FighterState.defeated:
      final fall = math.min(1.0, stateProgress * 2);
      return FighterPose(
        torsoAngle: -1.4 * fall,
        frontArmAngle: -0.6 * fall,
        backArmAngle: 0.8 * fall,
        frontLegAngle: 0.3 * fall,
        backLegAngle: -0.2 * fall,
        crouch: 0.85 * fall,
      );
  }
}

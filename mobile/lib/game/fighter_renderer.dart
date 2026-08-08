import 'dart:ui';

import 'fighter_rig.dart';

/// Desenha o "boneco" geométrico neon de um lutador a partir de uma
/// [FighterPose] -- só shapes simples (retângulos pros membros/tronco,
/// círculo pra cabeça), sem nenhum asset de imagem. Assume que o canvas já
/// está no espaço local do componente (0,0 = canto superior esquerdo da
/// caixa width x height) -- ver Fighter.render.
void renderFighterRig(
  Canvas canvas, {
  required FighterPose pose,
  required double width,
  required double height,
  required int facing,
  required Color bodyColor,
  required Color accentColor,
  required double opacity,
}) {
  final bodyPaint = Paint()..color = bodyColor.withValues(alpha: opacity);
  final accentPaint = Paint()..color = accentColor.withValues(alpha: opacity);
  final outlinePaint = Paint()
    ..color = accentColor.withValues(alpha: opacity)
    ..style = PaintingStyle.stroke
    ..strokeWidth = 2;

  final crouchOffset = pose.crouch * height * 0.12;
  final hipY = height * 0.62 - crouchOffset;
  final shoulderY = height * 0.30 - crouchOffset * 0.5;
  final headCenter = Offset(width / 2, height * 0.16 - crouchOffset * 0.5 + pose.headBobY);
  const headRadius = 18.0;
  final legLength = height * 0.32;
  final armLength = height * 0.26;

  // Ombros/quadris são DOIS pontos (esquerda/direita), não um só -- com um
  // pivô compartilhado, braço/perna da frente e de trás desenhavam quase
  // exatamente um em cima do outro (ângulos de poucos graus não bastam pra
  // separar visualmente dois retângulos saindo do MESMO ponto), o lutador
  // parecia ter 1 perna e nenhum braço visível. "Frente" sempre no lado
  // +x (a metade direita, já que o canvas abaixo é espelhado pra
  // facing==-1, então esse código sempre desenha como se estivesse de
  // frente pra direita).
  // shoulderOffsetX > a meia-largura do tronco (16, ver torsoRect abaixo)
  // de propósito -- senão os braços caem por dentro da silhueta do tronco
  // em vez de pendurados ao lado dele (só apareciam como "listras" sobre o
  // tronco, não como braços de verdade).
  const shoulderOffsetX = 21.0;
  const hipOffsetX = 10.0;
  final backHip = Offset(width / 2 - hipOffsetX, hipY);
  final frontHip = Offset(width / 2 + hipOffsetX, hipY);
  final backShoulder = Offset(width / 2 - shoulderOffsetX, shoulderY);
  final frontShoulder = Offset(width / 2 + shoulderOffsetX, shoulderY);

  canvas.save();
  // Espelha o desenho inteiro quando o lutador está de frente pra esquerda
  // -- assim todo o resto abaixo pode ser desenhado como se sempre olhasse
  // pra direita (facing == 1), sem duplicar a lógica de ângulo.
  canvas.translate(width / 2, 0);
  canvas.scale(facing.toDouble(), 1);
  canvas.translate(-width / 2, 0);

  // Pernas (a de trás primeiro, pra frente sobrepor se cruzarem).
  _drawLimb(canvas, backHip, pose.backLegAngle, legLength, 16, bodyPaint, outlinePaint);
  _drawLimb(canvas, frontHip, pose.frontLegAngle, legLength, 16, bodyPaint, outlinePaint);

  // Tronco: retângulo do meio do quadril ao meio do ombro, girado em torno
  // do quadril.
  canvas.save();
  final hipMid = Offset(width / 2, hipY);
  canvas.translate(hipMid.dx, hipMid.dy);
  canvas.rotate(pose.torsoAngle);
  final torsoHeight = hipY - shoulderY;
  final torsoRect = Rect.fromLTWH(-16, -torsoHeight, 32, torsoHeight);
  canvas.drawRRect(RRect.fromRectAndRadius(torsoRect, const Radius.circular(6)), bodyPaint);
  canvas.drawRRect(RRect.fromRectAndRadius(torsoRect, const Radius.circular(6)), outlinePaint);
  canvas.restore();

  // Cabeça.
  canvas.drawCircle(headCenter, headRadius, bodyPaint);
  canvas.drawCircle(headCenter, headRadius, outlinePaint);

  // Braços (o de trás primeiro).
  _drawLimb(canvas, backShoulder, pose.backArmAngle, armLength, 12, accentPaint, outlinePaint);
  _drawLimb(canvas, frontShoulder, pose.frontArmAngle, armLength, 12, accentPaint, outlinePaint);

  canvas.restore();
}

/// Um "membro" é só um retângulo pendurado de [pivot], apontando pra baixo
/// quando angle=0 e girando em torno do pivot conforme o ângulo (positivo =
/// gira a ponta pra frente/direita, já que o canvas já foi espelhado pra
/// facing==-1 antes de chegar aqui).
void _drawLimb(
  Canvas canvas,
  Offset pivot,
  double angle,
  double length,
  double thickness,
  Paint fillPaint,
  Paint outlinePaint,
) {
  canvas.save();
  canvas.translate(pivot.dx, pivot.dy);
  canvas.rotate(angle);
  final rect = Rect.fromLTWH(-thickness / 2, 0, thickness, length);
  final rrect = RRect.fromRectAndRadius(rect, Radius.circular(thickness / 2));
  canvas.drawRRect(rrect, fillPaint);
  canvas.drawRRect(rrect, outlinePaint);
  canvas.restore();
}

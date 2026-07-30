import 'package:flutter/material.dart';

class AppColors {
  AppColors._();

  static const neonBlue = Color(0xFF00E5FF);
  static const neonPurple = Color(0xFF9D4EDD);
  static const backgroundDark = Color(0xFF0B0B14);
  static const surfaceDark = Color(0xFF15151F);
  static const white = Color(0xFFF5F5FF);
  static const mutedWhite = Color(0xFFB8B8C8);
  static const success = Color(0xFF3DDC97);
  static const danger = Color(0xFFFF5C7A);
  // Cubo Épico -- roxo/magenta bem mais saturado que neonPurple, usado só
  // enquanto o bônus estiver ativo numa sessão (CubeVisual(epic: true) e o
  // painel/botão do Cubo Épico), pra destacar visualmente do roxo "normal"
  // do gradiente padrão do app.
  static const epicMagenta = Color(0xFFE026FF);
  static const epicGold = Color(0xFFFFD54A);
}

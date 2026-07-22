import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Fundo degradê roxo/azul/preto usado em todas as telas para o visual
/// futurista pedido no PRD.
class AppBackground extends StatelessWidget {
  const AppBackground({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: RadialGradient(
          center: Alignment.topRight,
          radius: 1.4,
          colors: [Color(0xFF2A1E5C), AppColors.backgroundDark, Colors.black],
          stops: [0.0, 0.55, 1.0],
        ),
      ),
      child: child,
    );
  }
}

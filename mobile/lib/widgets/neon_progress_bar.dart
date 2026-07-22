import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Barra de progresso com o gradiente neon azul->roxo, usada para mostrar o
/// avanço do ciclo de mineração até ends_at.
class NeonProgressBar extends StatelessWidget {
  const NeonProgressBar({super.key, required this.progress});

  /// 0.0 a 1.0.
  final double progress;

  @override
  Widget build(BuildContext context) {
    final clamped = progress.clamp(0.0, 1.0);
    return ClipRRect(
      borderRadius: BorderRadius.circular(999),
      child: Stack(
        children: [
          Container(height: 14, color: AppColors.surfaceDark),
          FractionallySizedBox(
            widthFactor: clamped,
            child: Container(
              height: 14,
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [AppColors.neonBlue, AppColors.neonPurple],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

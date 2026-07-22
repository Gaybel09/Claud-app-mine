import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Representação visual simples do cubo -- só a fundação; a arte final por
/// raridade fica pra quando o design entregar os assets.
class CubeVisual extends StatelessWidget {
  const CubeVisual({super.key, required this.type, this.glowing = false});

  final String type;
  final bool glowing;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 400),
      width: 160,
      height: 160,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppColors.neonBlue, AppColors.neonPurple],
        ),
        boxShadow: glowing
            ? [
                BoxShadow(
                  color: AppColors.neonBlue.withValues(alpha: 0.55),
                  blurRadius: 40,
                  spreadRadius: 4,
                ),
              ]
            : const [],
      ),
      child: Center(
        child: Text(
          type.toUpperCase(),
          style: const TextStyle(
            color: Colors.black,
            fontWeight: FontWeight.bold,
            letterSpacing: 1.2,
          ),
        ),
      ),
    );
  }
}

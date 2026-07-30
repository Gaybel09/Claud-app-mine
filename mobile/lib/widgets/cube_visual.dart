import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Representação visual simples do cubo -- só a fundação; a arte final por
/// raridade fica pra quando o design entregar os assets.
class CubeVisual extends StatelessWidget {
  const CubeVisual({super.key, required this.type, this.glowing = false, this.epic = false});

  final String type;
  final bool glowing;

  /// Cubo Épico ativo nesta sessão (session.epicBonusApplied) -- troca o
  /// gradiente pro roxo/magenta mais vibrante (AppColors.epicMagenta) e
  /// intensifica o brilho, até a mineração terminar ou ser coletada.
  final bool epic;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 400),
      width: 160,
      height: 160,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: epic
              ? const [AppColors.epicMagenta, AppColors.neonPurple]
              : const [AppColors.neonBlue, AppColors.neonPurple],
        ),
        boxShadow: glowing
            ? [
                BoxShadow(
                  color: (epic ? AppColors.epicMagenta : AppColors.neonBlue).withValues(alpha: 0.55),
                  blurRadius: epic ? 56 : 40,
                  spreadRadius: epic ? 6 : 4,
                ),
              ]
            : const [],
      ),
      child: Center(
        child: Text(
          type.toUpperCase(),
          textAlign: TextAlign.center,
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

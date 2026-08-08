import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Tela de vitória/derrota -- some assim que o resultado é decidido (ver
/// FightWorld.matchEndDelaySeconds), com opção de lutar de novo ou sair.
class FightResultOverlay extends StatelessWidget {
  const FightResultOverlay({super.key, required this.playerWon, required this.onRematch, required this.onExit});

  final bool playerWon;
  final VoidCallback onRematch;
  final VoidCallback onExit;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black.withValues(alpha: 0.78),
      alignment: Alignment.center,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            playerWon ? 'VITÓRIA!' : 'DERROTA',
            key: const Key('fight_result_text'),
            style: TextStyle(
              fontSize: 40,
              fontWeight: FontWeight.bold,
              color: playerWon ? AppColors.success : AppColors.danger,
            ),
          ),
          const SizedBox(height: 28),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              ElevatedButton(
                key: const Key('fight_rematch_button'),
                onPressed: onRematch,
                child: const Text('Lutar de novo'),
              ),
              const SizedBox(width: 16),
              OutlinedButton(
                key: const Key('fight_exit_button'),
                onPressed: onExit,
                child: const Text('Sair'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

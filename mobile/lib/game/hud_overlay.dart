import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import 'fighter.dart';

/// Barras de vida/energia dos dois lutadores, sempre visíveis durante a
/// luta -- jogador à esquerda (enche da esquerda pra direita), rival à
/// direita (enche da direita pra esquerda), convenção clássica de HUD de
/// luta simétrico.
class FightHud extends StatelessWidget {
  const FightHud({super.key, required this.player, required this.opponent});

  final Fighter player;
  final Fighter opponent;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(
          children: [
            Expanded(child: _FighterBars(fighter: player, alignEnd: false, label: 'VOCÊ')),
            const SizedBox(width: 16),
            Expanded(child: _FighterBars(fighter: opponent, alignEnd: true, label: 'RIVAL')),
          ],
        ),
      ),
    );
  }
}

class _FighterBars extends StatelessWidget {
  const _FighterBars({required this.fighter, required this.alignEnd, required this.label});

  final Fighter fighter;
  final bool alignEnd;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      // stretch (não start/end): os _StatBar abaixo dependem de largura
      // definida pro FractionallySizedBox interno calcular a fração certa.
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          label,
          textAlign: alignEnd ? TextAlign.right : TextAlign.left,
          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12),
        ),
        const SizedBox(height: 4),
        ValueListenableBuilder<int>(
          valueListenable: fighter.health,
          builder: (context, health, _) => _StatBar(
            key: Key(alignEnd ? 'fight_opponent_health_bar' : 'fight_player_health_bar'),
            ratio: health / fighter.attributes.maxHealth,
            color: AppColors.success,
            alignEnd: alignEnd,
          ),
        ),
        const SizedBox(height: 4),
        ValueListenableBuilder<double>(
          valueListenable: fighter.energy,
          builder: (context, energy, _) => _StatBar(
            key: Key(alignEnd ? 'fight_opponent_energy_bar' : 'fight_player_energy_bar'),
            ratio: energy / fighter.attributes.maxEnergy,
            color: AppColors.neonBlue,
            alignEnd: alignEnd,
            height: 6,
          ),
        ),
      ],
    );
  }
}

class _StatBar extends StatelessWidget {
  const _StatBar({super.key, required this.ratio, required this.color, required this.alignEnd, this.height = 14});

  final double ratio;
  final Color color;
  final bool alignEnd;
  final double height;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(999),
      child: Container(
        height: height,
        color: AppColors.surfaceDark,
        alignment: alignEnd ? Alignment.centerRight : Alignment.centerLeft,
        child: FractionallySizedBox(
          widthFactor: ratio.clamp(0.0, 1.0),
          child: Container(color: color),
        ),
      ),
    );
  }
}

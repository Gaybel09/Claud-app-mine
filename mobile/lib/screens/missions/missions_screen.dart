import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_exception.dart';
import '../../models/weekly_mission.dart';
import '../../services/missions_api.dart';
import '../../theme/app_colors.dart';

class MissionsScreen extends StatefulWidget {
  const MissionsScreen({super.key});

  @override
  State<MissionsScreen> createState() => _MissionsScreenState();
}

class _MissionsScreenState extends State<MissionsScreen> {
  late Future<WeeklyMission> _missionFuture;
  Timer? _tickTimer;

  @override
  void initState() {
    super.initState();
    _reload();
    // Só reconstrói a tela 1x/segundo pra atualizar a contagem regressiva
    // do multiplicador -- não refaz a requisição (isso só acontece em
    // _reload, puxado pelo pull-to-refresh ou ao reabrir a tela).
    _tickTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _tickTimer?.cancel();
    super.dispose();
  }

  void _reload() {
    final missionsApi = context.read<MissionsApi>();
    setState(() {
      _missionFuture = missionsApi.getWeeklyMission();
    });
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
        children: [
          Text('Missões', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 16),
          FutureBuilder<WeeklyMission>(
            future: _missionFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                return Text(
                  _errorMessage(snapshot.error),
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                );
              }
              final mission = snapshot.data!;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _WeeklyMissionCard(mission: mission),
                  if (mission.multiplierActive) ...[
                    const SizedBox(height: 16),
                    _MultiplierActiveCard(mission: mission),
                  ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _WeeklyMissionCard extends StatelessWidget {
  const _WeeklyMissionCard({required this.mission});

  final WeeklyMission mission;

  @override
  Widget build(BuildContext context) {
    final progressRatio = mission.progress / mission.target;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  mission.completed ? Icons.check_circle : Icons.flag_outlined,
                  color: mission.completed ? AppColors.success : AppColors.neonBlue,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Minere ${mission.target}x essa semana',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                key: const Key('weekly_mission_progress_bar'),
                value: progressRatio.clamp(0.0, 1.0),
                minHeight: 10,
                backgroundColor: AppColors.surfaceDark,
                valueColor: AlwaysStoppedAnimation(
                  mission.completed ? AppColors.success : AppColors.neonBlue,
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '${mission.progress}/${mission.target} coletas',
              key: const Key('weekly_mission_progress_text'),
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 4),
            Text(
              mission.completed
                  ? 'Missão concluída! Bônus de 1.5x liberado por 24h.'
                  : 'Complete pra ganhar 1.5x em todas as coletas pelas 24h seguintes.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.mutedWhite),
            ),
          ],
        ),
      ),
    );
  }
}

class _MultiplierActiveCard extends StatelessWidget {
  const _MultiplierActiveCard({required this.mission});

  final WeeklyMission mission;

  @override
  Widget build(BuildContext context) {
    final remaining = mission.multiplierExpiresAt!.difference(DateTime.now());
    final expired = remaining.isNegative;

    return Card(
      key: const Key('multiplier_active_card'),
      color: AppColors.epicGold.withValues(alpha: 0.18),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: AppColors.epicGold, width: 1.5),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            const Icon(Icons.bolt, color: AppColors.epicGold, size: 32),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Multiplicador ${mission.multiplier.toStringAsFixed(1)}x ativo!',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    expired ? 'Expirando...' : 'Acaba em ${_formatCountdown(remaining)}',
                    key: const Key('multiplier_countdown_text'),
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: AppColors.mutedWhite),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _formatCountdown(Duration remaining) {
  final hours = remaining.inHours;
  final minutes = remaining.inMinutes.remainder(60);
  final seconds = remaining.inSeconds.remainder(60);
  return '${hours}h ${minutes.toString().padLeft(2, '0')}m ${seconds.toString().padLeft(2, '0')}s';
}

String _errorMessage(Object? error) {
  if (error is ApiException) return error.message;
  return 'Não foi possível carregar a missão semanal.';
}

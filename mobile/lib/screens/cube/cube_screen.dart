import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../controllers/mining_controller.dart';
import '../../models/mining_session.dart';
import '../../services/ads_api.dart';
import '../../services/cubes_api.dart';
import '../../services/mining_api.dart';
import '../../services/rewarded_ad_service.dart';
import '../../theme/app_colors.dart';
import '../../widgets/cube_visual.dart';
import '../../widgets/neon_progress_bar.dart';

class CubeScreen extends StatefulWidget {
  const CubeScreen({
    super.key,
    this.adConfirmationPollInterval = const Duration(seconds: 2),
    this.miningStatusPollInterval = const Duration(seconds: 5),
  });

  /// Configuráveis para permitir testes de widget rápidos; em produção usam
  /// os defaults acima.
  final Duration adConfirmationPollInterval;
  final Duration miningStatusPollInterval;

  @override
  State<CubeScreen> createState() => _CubeScreenState();
}

class _CubeScreenState extends State<CubeScreen> {
  late final MiningController _controller;
  Timer? _progressTicker;
  double _progress = 0;

  @override
  void initState() {
    super.initState();
    _controller = MiningController(
      cubesApi: context.read<CubesApi>(),
      adsApi: context.read<AdsApi>(),
      miningApi: context.read<MiningApi>(),
      rewardedAdService: context.read<RewardedAdService>(),
      adConfirmationPollInterval: widget.adConfirmationPollInterval,
      miningStatusPollInterval: widget.miningStatusPollInterval,
    )..addListener(_onControllerChanged);
    _controller.loadCube();
  }

  void _onControllerChanged() {
    final session = _controller.session;
    if (session != null && _progressTicker == null) {
      _startProgressTicker(session);
    } else if (session == null) {
      _progressTicker?.cancel();
      _progressTicker = null;
    }
    setState(() {});
  }

  void _startProgressTicker(MiningSession session) {
    _updateProgress(session);
    _progressTicker = Timer.periodic(const Duration(seconds: 1), (_) {
      _updateProgress(session);
    });
  }

  void _updateProgress(MiningSession session) {
    final total = session.endsAt.difference(session.startedAt).inMilliseconds;
    final elapsed = DateTime.now().difference(session.startedAt).inMilliseconds;
    final value = total <= 0 ? 1.0 : elapsed / total;
    setState(() => _progress = value.clamp(0.0, 1.0));
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    _controller.dispose();
    _progressTicker?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Seu cubo', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 24),
          Expanded(child: Center(child: _buildBody(context))),
        ],
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final controller = _controller;

    if (controller.cube == null && controller.stage != CubeCycleStage.error) {
      return const CircularProgressIndicator();
    }

    switch (controller.stage) {
      case CubeCycleStage.idle:
        return _IdleState(cubeType: controller.cube!.type, onWatchAd: controller.watchAd);
      case CubeCycleStage.watchingAd:
        return const _MessageState(message: 'Carregando anúncio...', showSpinner: true);
      case CubeCycleStage.waitingAdConfirmation:
        return const _MessageState(
          message: 'Aguardando confirmação do anúncio...',
          showSpinner: true,
        );
      case CubeCycleStage.mining:
        return _MiningState(
          progress: _progress,
          endsAt: controller.session!.endsAt,
          session: controller.session!,
          epicBonusStage: controller.epicBonusStage,
          epicBonusError: controller.epicBonusError,
          onEpicBonus: controller.useEpicBonus,
          speedupStage: controller.speedupStage,
          speedupError: controller.speedupError,
          onSpeedup: controller.useSpeedup,
        );
      case CubeCycleStage.readyToCollect:
        return _ReadyState(onCollect: controller.collect);
      case CubeCycleStage.collecting:
        return const _MessageState(message: 'Coletando recompensa...', showSpinner: true);
      case CubeCycleStage.collected:
        return _CollectedState(
          amount: controller.lastRewardAmount ?? 0,
          onContinue: controller.resetToIdle,
        );
      case CubeCycleStage.error:
        return _ErrorState(
          message: controller.errorMessage ?? 'Erro desconhecido.',
          onRetry: controller.resetToIdle,
        );
    }
  }
}

class _IdleState extends StatelessWidget {
  const _IdleState({required this.cubeType, required this.onWatchAd});

  final String cubeType;
  final VoidCallback onWatchAd;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CubeVisual(type: cubeType),
        const SizedBox(height: 32),
        Text(
          'Assista a um anúncio para começar a minerar',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: 24),
        ElevatedButton(
          key: const Key('watch_ad_button'),
          onPressed: onWatchAd,
          child: const Text('ASSISTIR ANÚNCIO'),
        ),
      ],
    );
  }
}

class _MessageState extends StatelessWidget {
  const _MessageState({required this.message, this.showSpinner = false});

  final String message;
  final bool showSpinner;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (showSpinner) ...[
          const CircularProgressIndicator(),
          const SizedBox(height: 24),
        ],
        Text(message, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
      ],
    );
  }
}

class _MiningState extends StatelessWidget {
  const _MiningState({
    required this.progress,
    required this.endsAt,
    required this.session,
    required this.epicBonusStage,
    required this.epicBonusError,
    required this.onEpicBonus,
    required this.speedupStage,
    required this.speedupError,
    required this.onSpeedup,
  });

  final double progress;
  final DateTime endsAt;
  final MiningSession session;
  final BonusActionStage epicBonusStage;
  final String? epicBonusError;
  final VoidCallback onEpicBonus;
  final BonusActionStage speedupStage;
  final String? speedupError;
  final VoidCallback onSpeedup;

  @override
  Widget build(BuildContext context) {
    final remaining = endsAt.difference(DateTime.now());
    final remainingText = remaining.isNegative
        ? 'Finalizando...'
        : '${remaining.inHours}h ${remaining.inMinutes.remainder(60)}min restantes';

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const CubeVisual(type: 'minerando', glowing: true),
        const SizedBox(height: 32),
        NeonProgressBar(progress: progress),
        const SizedBox(height: 12),
        Text(remainingText, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 24),
        _BonusButton(
          buttonKey: const Key('epic_bonus_button'),
          label: 'Cubo Épico: assista mais um anúncio pra ganhar um bônus',
          visible: !session.epicBonusApplied,
          stage: epicBonusStage,
          errorMessage: epicBonusError,
          onPressed: onEpicBonus,
        ),
        const SizedBox(height: 12),
        _BonusButton(
          buttonKey: const Key('speedup_button'),
          label: 'Acelerar (2x): assista um anúncio',
          visible: !session.speedupUsed,
          stage: speedupStage,
          errorMessage: speedupError,
          onPressed: onSpeedup,
        ),
      ],
    );
  }
}

class _BonusButton extends StatelessWidget {
  const _BonusButton({
    required this.buttonKey,
    required this.label,
    required this.visible,
    required this.stage,
    required this.errorMessage,
    required this.onPressed,
  });

  final Key buttonKey;
  final String label;
  final bool visible;
  final BonusActionStage stage;
  final String? errorMessage;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    if (!visible) return const SizedBox.shrink();

    final isBusy =
        stage == BonusActionStage.watchingAd || stage == BonusActionStage.waitingConfirmation;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        OutlinedButton(
          key: buttonKey,
          onPressed: isBusy ? null : onPressed,
          child: isBusy
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Text(label, textAlign: TextAlign.center),
        ),
        if (stage == BonusActionStage.error && errorMessage != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              errorMessage!,
              style: TextStyle(color: Theme.of(context).colorScheme.error, fontSize: 12),
              textAlign: TextAlign.center,
            ),
          ),
      ],
    );
  }
}

class _ReadyState extends StatelessWidget {
  const _ReadyState({required this.onCollect});

  final VoidCallback onCollect;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const CubeVisual(type: 'pronto', glowing: true),
        const SizedBox(height: 32),
        Text(
          'Seu cubo está pronto para coleta!',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: 24),
        ElevatedButton(
          key: const Key('collect_button'),
          onPressed: onCollect,
          child: const Text('COLETAR'),
        ),
      ],
    );
  }
}

class _CollectedState extends StatelessWidget {
  const _CollectedState({required this.amount, required this.onContinue});

  final double amount;
  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.celebration, color: AppColors.success, size: 64),
        const SizedBox(height: 16),
        Text(
          'Você ganhou R\$ ${amount.toStringAsFixed(2)}!',
          key: const Key('reward_amount_text'),
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 24),
        ElevatedButton(onPressed: onContinue, child: const Text('MINERAR DE NOVO')),
      ],
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.error_outline, color: Theme.of(context).colorScheme.error, size: 48),
        const SizedBox(height: 16),
        Text(
          message,
          key: const Key('cube_error_text'),
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: 24),
        ElevatedButton(onPressed: onRetry, child: const Text('TENTAR DE NOVO')),
      ],
    );
  }
}

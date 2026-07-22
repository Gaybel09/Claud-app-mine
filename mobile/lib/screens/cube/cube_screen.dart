import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../controllers/mining_controller.dart';
import '../../models/mining_session.dart';
import '../../services/ads_api.dart';
import '../../services/cubes_api.dart';
import '../../services/mining_api.dart';
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
        return _MiningState(progress: _progress, endsAt: controller.session!.endsAt);
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
  const _MiningState({required this.progress, required this.endsAt});

  final double progress;
  final DateTime endsAt;

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

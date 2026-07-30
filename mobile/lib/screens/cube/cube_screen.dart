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
  // endsAt que o _progressTicker atual está usando -- comparado a cada
  // notifyListeners() pra saber se precisa reiniciar o ticker (ver
  // _onControllerChanged). Sem isso, usar o Acelerar (que muda
  // session.endsAt no meio da mineração) não tinha efeito nenhum na barra
  // de progresso: o Timer.periodic já rodando desde o início da mineração
  // fecha sobre o objeto MiningSession de ENTÃO, e só reiniciava quando
  // _progressTicker == null -- ou seja, nunca de novo depois do primeiro
  // start. O texto "Xh Ymin restantes" (recalculado do zero a cada rebuild
  // em _MiningState) sempre mostrava o valor certo; só a barra visual
  // ficava presa na trajetória antiga, sem refletir a redução real do
  // tempo.
  DateTime? _tickedEndsAt;

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
    if (session != null && (_progressTicker == null || _tickedEndsAt != session.endsAt)) {
      _startProgressTicker(session);
    } else if (session == null) {
      _progressTicker?.cancel();
      _progressTicker = null;
      _tickedEndsAt = null;
    }
    setState(() {});
  }

  void _startProgressTicker(MiningSession session) {
    _progressTicker?.cancel();
    _tickedEndsAt = session.endsAt;
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
        return _ReadyState(
          onCollect: controller.collect,
          epic: controller.session?.epicBonusApplied ?? false,
        );
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
    final isEpic = session.epicBonusApplied;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CubeVisual(
          type: isEpic ? 'épico minerando' : 'minerando',
          glowing: true,
          epic: isEpic,
        ),
        const SizedBox(height: 32),
        NeonProgressBar(progress: progress),
        const SizedBox(height: 12),
        Text(remainingText, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 24),
        _EpicBonusPanel(
          videosWatched: session.epicBonusVideosWatched,
          applied: session.epicBonusApplied,
          stage: epicBonusStage,
          errorMessage: epicBonusError,
          onWatchVideo: onEpicBonus,
        ),
        const SizedBox(height: 16),
        _SpeedupButton(
          visible: !session.speedupUsed,
          stage: speedupStage,
          errorMessage: speedupError,
          onPressed: onSpeedup,
        ),
      ],
    );
  }
}

/// Botão de ação "chamativo" coerente com o tema neon do app -- gradiente,
/// ícone e brilho -- reaproveitado pelo Cubo Épico e pelo Acelerar em vez
/// de um OutlinedButton genérico.
class _GlowActionButton extends StatelessWidget {
  const _GlowActionButton({
    required this.buttonKey,
    required this.icon,
    required this.label,
    required this.gradientColors,
    required this.glowColor,
    required this.busy,
    required this.onPressed,
  });

  final Key buttonKey;
  final IconData icon;
  final String label;
  final List<Color> gradientColors;
  final Color glowColor;
  final bool busy;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        key: buttonKey,
        borderRadius: BorderRadius.circular(16),
        onTap: busy ? null : onPressed,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: LinearGradient(colors: gradientColors),
            boxShadow: busy
                ? const []
                : [BoxShadow(color: glowColor.withValues(alpha: 0.5), blurRadius: 22, spreadRadius: 1)],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (busy)
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                )
              else
                Icon(icon, color: Colors.black, size: 20),
              const SizedBox(width: 10),
              Flexible(
                child: Text(
                  label,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Cubo Épico -- fluxo de desbloqueio: enquanto epicBonusVideosRequired (2)
/// vídeos não forem assistidos, mostra a mensagem + indicador de progresso
/// (bolinhas) + botão pra assistir o próximo. Depois dos dois, mostra o
/// badge de "liberado" (ver _EpicBonusUnlockedBadge) e some com o botão.
class _EpicBonusPanel extends StatelessWidget {
  const _EpicBonusPanel({
    required this.videosWatched,
    required this.applied,
    required this.stage,
    required this.errorMessage,
    required this.onWatchVideo,
  });

  final int videosWatched;
  final bool applied;
  final BonusActionStage stage;
  final String? errorMessage;
  final VoidCallback onWatchVideo;

  @override
  Widget build(BuildContext context) {
    if (applied) {
      return const _EpicBonusUnlockedBadge();
    }

    final busy = stage == BonusActionStage.watchingAd || stage == BonusActionStage.waitingConfirmation;
    final nextVideoNumber = videosWatched + 1;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'Assista $epicBonusVideosRequired vídeos para desbloquear o Cubo Épico',
          key: const Key('epic_bonus_progress_text'),
          textAlign: TextAlign.center,
          style: Theme.of(context)
              .textTheme
              .bodyMedium
              ?.copyWith(color: AppColors.epicMagenta, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        _EpicBonusDots(videosWatched: videosWatched),
        const SizedBox(height: 12),
        _GlowActionButton(
          buttonKey: const Key('epic_bonus_button'),
          icon: Icons.auto_awesome,
          label: 'Assistir vídeo $nextVideoNumber/$epicBonusVideosRequired',
          gradientColors: const [AppColors.epicMagenta, AppColors.neonPurple],
          glowColor: AppColors.epicMagenta,
          busy: busy,
          onPressed: onWatchVideo,
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

class _EpicBonusDots extends StatelessWidget {
  const _EpicBonusDots({required this.videosWatched});

  final int videosWatched;

  @override
  Widget build(BuildContext context) {
    return Row(
      key: const Key('epic_bonus_dots'),
      mainAxisSize: MainAxisSize.min,
      children: List.generate(epicBonusVideosRequired, (index) {
        final filled = index < videosWatched;
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Icon(
            filled ? Icons.circle : Icons.circle_outlined,
            size: 14,
            color: filled ? AppColors.epicMagenta : AppColors.mutedWhite,
          ),
        );
      }),
    );
  }
}

class _EpicBonusUnlockedBadge extends StatelessWidget {
  const _EpicBonusUnlockedBadge();

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      key: const Key('epic_bonus_unlocked_badge'),
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 500),
      curve: Curves.easeOut,
      builder: (context, value, child) {
        return Opacity(
          opacity: value,
          child: Transform.scale(scale: 0.85 + 0.15 * value, child: child),
        );
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(999),
          gradient: const LinearGradient(colors: [AppColors.epicMagenta, AppColors.epicGold]),
          boxShadow: [
            BoxShadow(color: AppColors.epicMagenta.withValues(alpha: 0.5), blurRadius: 24, spreadRadius: 2),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.auto_awesome, color: Colors.black, size: 20),
            const SizedBox(width: 8),
            Text(
              'Cubo Épico liberado!',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: Colors.black, fontWeight: FontWeight.bold),
            ),
          ],
        ),
      ),
    );
  }
}

class _SpeedupButton extends StatelessWidget {
  const _SpeedupButton({
    required this.visible,
    required this.stage,
    required this.errorMessage,
    required this.onPressed,
  });

  final bool visible;
  final BonusActionStage stage;
  final String? errorMessage;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    if (!visible) return const SizedBox.shrink();

    final busy = stage == BonusActionStage.watchingAd || stage == BonusActionStage.waitingConfirmation;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        _GlowActionButton(
          buttonKey: const Key('speedup_button'),
          icon: Icons.bolt,
          label: 'Acelerar (2x): assista um anúncio',
          gradientColors: const [AppColors.neonBlue, AppColors.neonPurple],
          glowColor: AppColors.neonBlue,
          busy: busy,
          onPressed: onPressed,
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
  const _ReadyState({required this.onCollect, this.epic = false});

  final VoidCallback onCollect;
  final bool epic;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CubeVisual(type: epic ? 'épico pronto' : 'pronto', glowing: true, epic: epic),
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

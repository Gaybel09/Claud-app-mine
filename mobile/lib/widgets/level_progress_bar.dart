import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/level_status.dart';
import '../services/levels_api.dart';
import '../theme/app_colors.dart';

/// Card com o nível atual e uma barra de XP animada -- exibido no topo da
/// tela principal (Cubo). Busca o próprio estado (independente do
/// MiningController), e opcionalmente reconsulta sempre que [refreshOn]
/// notifica -- usado pelo CubeScreen pra atualizar o XP assim que uma
/// coleta termina, sem precisar de nenhum acoplamento direto com o fluxo
/// de mineração.
class LevelProgressCard extends StatefulWidget {
  const LevelProgressCard({super.key, this.refreshOn});

  final Listenable? refreshOn;

  @override
  State<LevelProgressCard> createState() => _LevelProgressCardState();
}

class _LevelProgressCardState extends State<LevelProgressCard> {
  late Future<LevelStatus> _levelFuture;

  @override
  void initState() {
    super.initState();
    _reload();
    widget.refreshOn?.addListener(_reload);
  }

  @override
  void dispose() {
    widget.refreshOn?.removeListener(_reload);
    super.dispose();
  }

  void _reload() {
    final levelsApi = context.read<LevelsApi>();
    // Corpo de bloco (não seta) de propósito: `setState(() => x = future)`
    // devolve o valor da própria atribuição -- ou seja, o Future -- e o
    // Flutter lança exatamente por isso ("setState() callback argument
    // returned a Future").
    setState(() {
      _levelFuture = levelsApi.getMyLevel();
    });
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<LevelStatus>(
      future: _levelFuture,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          // Sem spinner próprio -- é só um card secundário no topo da
          // tela principal, cujo conteúdo real (mineração) já tem o
          // próprio carregamento; evita duas rodas de progresso
          // competindo por atenção na mesma tela.
          return const SizedBox(height: 64);
        }
        if (snapshot.hasError) {
          return const SizedBox.shrink();
        }
        return _LevelCard(status: snapshot.data!);
      },
    );
  }
}

class _LevelCard extends StatelessWidget {
  const _LevelCard({required this.status});

  final LevelStatus status;

  @override
  Widget build(BuildContext context) {
    final ratio = status.xpForNextLevel == 0 ? 0.0 : status.xpIntoLevel / status.xpForNextLevel;

    return Card(
      key: const Key('level_progress_card'),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            _LevelBadge(level: status.level),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _AnimatedNeonBar(ratio: ratio),
                  const SizedBox(height: 4),
                  Text(
                    '${status.xpIntoLevel}/${status.xpForNextLevel} XP',
                    key: const Key('level_progress_xp_text'),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.mutedWhite),
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

class _LevelBadge extends StatelessWidget {
  const _LevelBadge({required this.level});

  final int level;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 48,
      height: 48,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppColors.neonBlue, AppColors.neonPurple],
        ),
        boxShadow: [
          BoxShadow(color: AppColors.neonPurple.withValues(alpha: 0.5), blurRadius: 12, spreadRadius: 1),
        ],
      ),
      child: Text(
        '$level',
        key: const Key('level_progress_level_text'),
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Colors.white),
      ),
    );
  }
}

/// Barra neon que anima suavemente até a nova fração sempre que [ratio]
/// muda -- em vez de simplesmente saltar pro novo valor (como a barra de
/// progresso da mineração, que atualiza a cada segundo e não precisa
/// disso), já que XP muda em saltos pouco frequentes (cada coleta), onde
/// uma transição suave se nota e fica mais bonita.
class _AnimatedNeonBar extends StatelessWidget {
  const _AnimatedNeonBar({required this.ratio});

  final double ratio;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(999),
      child: Stack(
        children: [
          Container(height: 12, color: AppColors.surfaceDark),
          TweenAnimationBuilder<double>(
            key: const Key('level_progress_bar'),
            tween: Tween(begin: 0, end: ratio.clamp(0.0, 1.0)),
            duration: const Duration(milliseconds: 800),
            curve: Curves.easeOutCubic,
            builder: (context, value, child) {
              return FractionallySizedBox(
                widthFactor: value,
                child: Container(
                  height: 12,
                  decoration: const BoxDecoration(
                    gradient: LinearGradient(
                      colors: [AppColors.neonBlue, AppColors.neonPurple],
                    ),
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}


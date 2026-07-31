import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_exception.dart';
import '../../models/app_user.dart';
import '../../models/ranking.dart';
import '../../services/auth_api.dart';
import '../../services/ranking_api.dart';
import '../../theme/app_colors.dart';

class RankingScreen extends StatefulWidget {
  const RankingScreen({super.key});

  @override
  State<RankingScreen> createState() => _RankingScreenState();
}

class _RankingScreenData {
  const _RankingScreenData(this.ranking, this.user);

  final RankingResult ranking;
  final AppUser user;
}

class _RankingScreenState extends State<RankingScreen> {
  late Future<_RankingScreenData> _dataFuture;
  bool _showRegional = false;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    final rankingApi = context.read<RankingApi>();
    final authApi = context.read<AuthApi>();
    setState(() {
      _dataFuture = Future.wait<Object>([rankingApi.getRanking(), authApi.login()]).then(
        (results) => _RankingScreenData(results[0] as RankingResult, results[1] as AppUser),
      );
    });
  }

  Future<void> _editNickname(String? current) async {
    final controller = TextEditingController(text: current ?? '');
    final result = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Definir apelido'),
        content: TextField(
          controller: controller,
          key: const Key('nickname_input'),
          maxLength: 32,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'Como quer aparecer no ranking?'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancelar'),
          ),
          TextButton(
            key: const Key('nickname_save_button'),
            onPressed: () => Navigator.of(dialogContext).pop(controller.text.trim()),
            child: const Text('Salvar'),
          ),
        ],
      ),
    );
    if (result == null || result.isEmpty || !mounted) return;

    try {
      await context.read<AuthApi>().updateNickname(result);
      _reload();
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
        children: [
          Text('Ranking', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 16),
          FutureBuilder<_RankingScreenData>(
            future: _dataFuture,
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
              final data = snapshot.data!;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _NicknameCard(
                    nickname: data.user.nickname,
                    onEdit: () => _editNickname(data.user.nickname),
                  ),
                  const SizedBox(height: 24),
                  if (data.ranking.regional != null) ...[
                    _ScopeToggle(
                      regionLabel: data.ranking.regional!.regionLabel,
                      showRegional: _showRegional,
                      onChanged: (value) => setState(() => _showRegional = value),
                    ),
                    const SizedBox(height: 16),
                  ],
                  _ScopeRankingView(
                    scope: _showRegional ? data.ranking.regional! : data.ranking.general,
                    currentUserId: data.user.id,
                  ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _NicknameCard extends StatelessWidget {
  const _NicknameCard({required this.nickname, required this.onEdit});

  final String? nickname;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.badge_outlined, color: AppColors.neonBlue),
        title: Text(
          nickname ?? 'Defina um apelido',
          key: const Key('nickname_display_text'),
        ),
        subtitle: Text(
          nickname == null ? 'Aparece no ranking no lugar do seu e-mail' : 'Seu nome no ranking',
        ),
        trailing: IconButton(
          key: const Key('edit_nickname_button'),
          icon: const Icon(Icons.edit),
          onPressed: onEdit,
        ),
      ),
    );
  }
}

class _ScopeToggle extends StatelessWidget {
  const _ScopeToggle({required this.regionLabel, required this.showRegional, required this.onChanged});

  final String regionLabel;
  final bool showRegional;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ChoiceChip(
          key: const Key('ranking_scope_general_chip'),
          label: const Text('Geral'),
          selected: !showRegional,
          onSelected: (_) => onChanged(false),
        ),
        const SizedBox(width: 8),
        ChoiceChip(
          key: const Key('ranking_scope_regional_chip'),
          label: Text(regionLabel),
          selected: showRegional,
          onSelected: (_) => onChanged(true),
        ),
      ],
    );
  }
}

class _ScopeRankingView extends StatelessWidget {
  const _ScopeRankingView({required this.scope, required this.currentUserId});

  final ScopeRanking scope;
  final int currentUserId;

  @override
  Widget build(BuildContext context) {
    final myEntryInTop = scope.top.any((entry) => entry.userId == currentUserId);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (scope.top.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 24),
            child: Text(
              'Ninguém no ranking ainda -- minere para aparecer aqui!',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          )
        else
          ...scope.top.map(
            (entry) => _RankingTile(entry: entry, highlighted: entry.userId == currentUserId),
          ),
        if (!myEntryInTop && scope.myRank != null) ...[
          const SizedBox(height: 8),
          _RankingTile(
            entry: RankingEntry(
              rank: scope.myRank!,
              userId: currentUserId,
              displayName: 'Você',
              total: scope.myTotal,
            ),
            highlighted: true,
          ),
        ],
        if (scope.myRank == null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              'Você ainda não pontuou neste ranking -- minere para entrar!',
              key: const Key('ranking_no_score_text'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
      ],
    );
  }
}

class _RankingTile extends StatelessWidget {
  const _RankingTile({required this.entry, required this.highlighted});

  final RankingEntry entry;
  final bool highlighted;

  static const _medalColors = {
    1: Color(0xFFFFD54A),
    2: Color(0xFFC0C0C0),
    3: Color(0xFFCD7F32),
  };

  @override
  Widget build(BuildContext context) {
    return Card(
      key: highlighted ? const Key('ranking_my_position_tile') : null,
      margin: const EdgeInsets.only(bottom: 8),
      color: highlighted ? AppColors.neonPurple.withValues(alpha: 0.25) : null,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: highlighted ? const BorderSide(color: AppColors.neonBlue, width: 1.5) : BorderSide.none,
      ),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: _medalColors[entry.rank] ?? AppColors.surfaceDark,
          child: Text(
            '${entry.rank}',
            style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.black),
          ),
        ),
        title: Text(
          entry.displayName,
          style: TextStyle(fontWeight: highlighted ? FontWeight.bold : FontWeight.normal),
        ),
        trailing: Text(
          'R\$ ${entry.total.toStringAsFixed(2)}',
          style: const TextStyle(fontWeight: FontWeight.bold, color: AppColors.success),
        ),
      ),
    );
  }
}

String _errorMessage(Object? error) {
  if (error is ApiException) return error.message;
  return 'Não foi possível carregar o ranking.';
}

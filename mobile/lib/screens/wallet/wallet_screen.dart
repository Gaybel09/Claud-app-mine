import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../core/api_exception.dart';
import '../../models/ledger_entry.dart';
import '../../services/wallet_api.dart';
import '../../theme/app_colors.dart';

class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key});

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  late Future<double> _balanceFuture;
  late Future<Statement> _statementFuture;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    final walletApi = context.read<WalletApi>();
    setState(() {
      _balanceFuture = walletApi.getBalance();
      _statementFuture = walletApi.getStatement();
    });
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _reload(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
        children: [
          Text('Carteira', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 16),
          _BalanceCard(balanceFuture: _balanceFuture),
          const SizedBox(height: 32),
          Text('Extrato', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          _StatementList(statementFuture: _statementFuture),
        ],
      ),
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.balanceFuture});

  final Future<double> balanceFuture;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: FutureBuilder<double>(
          future: balanceFuture,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Text(
                _errorMessage(snapshot.error),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              );
            }
            final balance = snapshot.data ?? 0;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Saldo disponível', style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(height: 8),
                Text(
                  'R\$ ${balance.toStringAsFixed(2)}',
                  key: const Key('wallet_balance_text'),
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                        color: AppColors.neonBlue,
                        fontWeight: FontWeight.bold,
                      ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _StatementList extends StatelessWidget {
  const _StatementList({required this.statementFuture});

  final Future<Statement> statementFuture;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Statement>(
      future: statementFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 32),
            child: Center(child: CircularProgressIndicator()),
          );
        }
        if (snapshot.hasError) {
          return Text(
            _errorMessage(snapshot.error),
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          );
        }
        final items = snapshot.data?.items ?? const [];
        if (items.isEmpty) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 32),
            child: Text(
              'Nenhuma movimentação ainda.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          );
        }
        return Column(
          children: items.map((entry) => _LedgerEntryTile(entry: entry)).toList(),
        );
      },
    );
  }
}

class _LedgerEntryTile extends StatelessWidget {
  const _LedgerEntryTile({required this.entry});

  final LedgerEntry entry;

  static const _labels = {
    'reward': 'Recompensa',
    'withdrawal': 'Saque',
    'bonus': 'Bônus',
    'fee': 'Taxa',
  };

  @override
  Widget build(BuildContext context) {
    final isCredit = entry.amount >= 0;
    final color = isCredit ? AppColors.success : AppColors.danger;
    final sign = isCredit ? '+' : '';
    final dateFormat = DateFormat('dd/MM/yyyy HH:mm');

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Icon(
          isCredit ? Icons.arrow_downward : Icons.arrow_upward,
          color: color,
        ),
        title: Text(_labels[entry.type] ?? entry.type),
        subtitle: Text(dateFormat.format(entry.createdAt.toLocal())),
        trailing: Text(
          '$sign R\$ ${entry.amount.toStringAsFixed(2)}',
          style: TextStyle(color: color, fontWeight: FontWeight.bold),
        ),
      ),
    );
  }
}

String _errorMessage(Object? error) {
  if (error is ApiException) return error.message;
  return 'Não foi possível carregar os dados.';
}

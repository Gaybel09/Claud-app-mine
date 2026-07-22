import 'package:cubemine_pix/models/ledger_entry.dart';
import 'package:cubemine_pix/screens/wallet/wallet_screen.dart';
import 'package:cubemine_pix/services/wallet_api.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

void main() {
  group('WalletScreen', () {
    testWidgets('shows the balance and the statement entries', (tester) async {
      final walletApi = FakeWalletApi()
        ..balance = 42.5
        ..statement = Statement(
          items: [
            LedgerEntry(
              id: 1,
              type: 'reward',
              amount: 0.55,
              referenceId: '10',
              balanceAfter: 42.5,
              createdAt: DateTime.now(),
            ),
            LedgerEntry(
              id: 2,
              type: 'withdrawal',
              amount: -5.0,
              referenceId: null,
              balanceAfter: 41.95,
              createdAt: DateTime.now(),
            ),
          ],
          page: 1,
          pageSize: 20,
          total: 2,
        );

      await tester.pumpWidget(
        MultiProvider(
          providers: [Provider<WalletApi>.value(value: walletApi)],
          child: MaterialApp(theme: AppTheme.dark, home: const WalletScreen()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('R\$ 42.50'), findsOneWidget);
      expect(find.text('Recompensa'), findsOneWidget);
      expect(find.text('Saque'), findsOneWidget);
    });

    testWidgets('shows an error message when the balance call fails', (tester) async {
      final walletApi = FakeWalletApi()..throwOnBalance = Exception('network error');

      await tester.pumpWidget(
        MultiProvider(
          providers: [Provider<WalletApi>.value(value: walletApi)],
          child: MaterialApp(theme: AppTheme.dark, home: const WalletScreen()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Não foi possível carregar os dados.'), findsOneWidget);
    });
  });
}

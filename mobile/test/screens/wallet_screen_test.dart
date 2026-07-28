import 'package:cubemine_pix/models/ledger_entry.dart';
import 'package:cubemine_pix/models/withdrawal.dart';
import 'package:cubemine_pix/screens/wallet/wallet_screen.dart';
import 'package:cubemine_pix/services/auth_api.dart';
import 'package:cubemine_pix/services/pix_api.dart';
import 'package:cubemine_pix/services/wallet_api.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

Widget _wrap({
  required FakeWalletApi walletApi,
  required FakePixApi pixApi,
  FakeAuthApi? authApi,
}) {
  return MultiProvider(
    providers: [
      Provider<WalletApi>.value(value: walletApi),
      Provider<PixApi>.value(value: pixApi),
      Provider<AuthApi>.value(value: authApi ?? FakeAuthApi()),
    ],
    child: MaterialApp(theme: AppTheme.dark, home: const WalletScreen()),
  );
}

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

      await tester.pumpWidget(_wrap(walletApi: walletApi, pixApi: FakePixApi()));
      await tester.pumpAndSettle();

      expect(find.text('R\$ 42.50'), findsOneWidget);
      expect(find.text('Recompensa'), findsOneWidget);
      expect(find.text('Saque'), findsOneWidget);
    });

    testWidgets('shows an error message when the balance call fails', (tester) async {
      final walletApi = FakeWalletApi()..throwOnBalance = Exception('network error');

      await tester.pumpWidget(_wrap(walletApi: walletApi, pixApi: FakePixApi()));
      await tester.pumpAndSettle();

      expect(find.text('Não foi possível carregar os dados.'), findsOneWidget);
    });

    testWidgets('shows the "Sacar" button only when the balance is above zero', (tester) async {
      final walletApi = FakeWalletApi()..balance = 0;
      await tester.pumpWidget(_wrap(walletApi: walletApi, pixApi: FakePixApi()));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('withdraw_button')), findsNothing);
    });

    testWidgets('shows the "Sacar" button when there is an available balance', (tester) async {
      final walletApi = FakeWalletApi()..balance = 42.5;
      await tester.pumpWidget(_wrap(walletApi: walletApi, pixApi: FakePixApi()));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('withdraw_button')), findsOneWidget);
    });

    testWidgets('lists withdrawals with their status, including ones not in the ledger yet', (tester) async {
      // saques pending/processing ainda não geram LedgerEntry (só quando
      // paid) -- por isso precisam de uma lista própria, não só o Extrato.
      final walletApi = FakeWalletApi()..balance = 10;
      final pixApi = FakePixApi()
        ..listWithdrawalsQueue = [
          [
            Withdrawal(
              id: 1,
              userId: 1,
              amount: 15,
              pixKey: 'user@example.com',
              status: 'processing',
              idempotencyKey: 'k1',
              createdAt: DateTime.now(),
            ),
          ],
        ];

      await tester.pumpWidget(_wrap(walletApi: walletApi, pixApi: pixApi));
      await tester.pumpAndSettle();

      expect(find.text('R\$ 15.00'), findsOneWidget);
      expect(find.byKey(const Key('withdrawal_status_label')), findsOneWidget);
      expect(find.text('Processando'), findsOneWidget);
    });

    testWidgets('tapping "Sacar" opens the withdraw screen', (tester) async {
      final walletApi = FakeWalletApi()..balance = 42.5;
      await tester.pumpWidget(_wrap(walletApi: walletApi, pixApi: FakePixApi()));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('withdraw_button')));
      await tester.pumpAndSettle();

      expect(find.text('Sacar'), findsOneWidget);
      expect(find.byKey(const Key('withdraw_amount_field')), findsOneWidget);
    });
  });
}

import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/models/withdrawal.dart';
import 'package:cubemine_pix/screens/wallet/withdraw_screen.dart';
import 'package:cubemine_pix/services/auth_api.dart';
import 'package:cubemine_pix/services/pix_api.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

Widget _wrap({
  required FakePixApi pixApi,
  required FakeAuthApi authApi,
  double availableBalance = 100,
}) {
  return MultiProvider(
    providers: [
      Provider<PixApi>.value(value: pixApi),
      Provider<AuthApi>.value(value: authApi),
    ],
    child: MaterialApp(
      theme: AppTheme.dark,
      home: WithdrawScreen(availableBalance: availableBalance),
    ),
  );
}

Withdrawal _withdrawal({String status = 'processing', double amount = 30}) {
  return Withdrawal(
    id: 1,
    userId: 1,
    amount: amount,
    pixKey: 'user@example.com',
    status: status,
    idempotencyKey: 'key-1',
    createdAt: DateTime.now(),
  );
}

void main() {
  group('WithdrawScreen', () {
    testWidgets('shows the registered Pix key instead of an input field', (tester) async {
      final pixApi = FakePixApi();
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      expect(find.textContaining('user@example.com'), findsOneWidget);
      expect(find.byKey(const Key('withdraw_pix_key_field')), findsNothing);
    });

    testWidgets('shows a Pix key field when the user has none registered yet', (tester) async {
      final pixApi = FakePixApi();
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('withdraw_pix_key_field')), findsOneWidget);
    });

    testWidgets('rejects an amount above the available balance before calling the API', (tester) async {
      final pixApi = FakePixApi();
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi, availableBalance: 50));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '999');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      expect(find.text('Valor maior que o saldo disponível.'), findsOneWidget);
      expect(pixApi.withdrawCallCount, 0);
    });

    testWidgets('requires a Pix key when none is registered yet', (tester) async {
      final pixApi = FakePixApi();
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '10');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      expect(find.text('Informe sua chave Pix.'), findsOneWidget);
      expect(pixApi.withdrawCallCount, 0);
    });

    testWidgets('submits amount and the typed Pix key when the user has none registered', (tester) async {
      final pixApi = FakePixApi()..withdrawResult = _withdrawal(status: 'paid');
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '30');
      await tester.enterText(find.byKey(const Key('withdraw_pix_key_field')), 'new-key@example.com');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      expect(pixApi.withdrawCallCount, 1);
      expect(pixApi.lastAmount, 30);
      expect(pixApi.lastPixKey, 'new-key@example.com');
      expect(find.byKey(const Key('withdraw_done_message')), findsOneWidget);
      expect(find.textContaining('confirmado'), findsOneWidget);
    });

    testWidgets('submits with pixKey omitted when the user already has one registered', (tester) async {
      final pixApi = FakePixApi()..withdrawResult = _withdrawal(status: 'paid');
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '30');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      expect(pixApi.lastPixKey, isNull);
      expect(pixApi.lastAmount, 30);
    });

    testWidgets('shows a processing message while the withdrawal has not settled yet', (tester) async {
      final pixApi = FakePixApi()
        ..withdrawResult = _withdrawal(status: 'processing')
        ..listWithdrawalsQueue = [
          [_withdrawal(status: 'processing')],
        ];
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '30');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pump();

      expect(find.byKey(const Key('withdraw_processing_message')), findsOneWidget);
    });

    testWidgets('shows a friendly message for insufficient balance', (tester) async {
      final pixApi = FakePixApi()
        ..throwOnWithdraw = const ApiException(statusCode: 400, message: 'insufficient balance');
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '30');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('withdraw_error_text')), findsOneWidget);
      expect(find.textContaining('Saldo insuficiente'), findsOneWidget);
    });

    testWidgets('shows a friendly message when the withdraw rate limit is hit', (tester) async {
      final pixApi = FakePixApi()
        ..throwOnWithdraw = const ApiException(statusCode: 429, message: '5 per 1 hour');
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '30');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      expect(find.textContaining('Limite'), findsOneWidget);
    });

    testWidgets('tapping "tentar de novo" after an error goes back to the form', (tester) async {
      final pixApi = FakePixApi()
        ..throwOnWithdraw = const ApiException(statusCode: 400, message: 'insufficient balance');
      final authApi = FakeAuthApi()..pixKeyToReturn = 'user@example.com';
      await tester.pumpWidget(_wrap(pixApi: pixApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('withdraw_amount_field')), '30');
      await tester.tap(find.byKey(const Key('withdraw_submit_button')));
      await tester.pumpAndSettle();

      await tester.tap(find.text('TENTAR DE NOVO'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('withdraw_submit_button')), findsOneWidget);
    });
  });
}

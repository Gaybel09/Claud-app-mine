import 'package:cubemine_pix/controllers/withdraw_controller.dart';
import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/models/withdrawal.dart';
import 'package:flutter_test/flutter_test.dart';

import '../fakes/fake_services.dart';

Future<void> _waitUntil(
  bool Function() condition, {
  Duration timeout = const Duration(seconds: 2),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      fail('Condition not met within $timeout');
    }
    await Future.delayed(const Duration(milliseconds: 5));
  }
}

Withdrawal _withdrawal({int id = 1, String status = 'processing', double amount = 10}) {
  return Withdrawal(
    id: id,
    userId: 1,
    amount: amount,
    pixKey: 'user@example.com',
    status: status,
    idempotencyKey: 'key-$id',
    createdAt: DateTime.now(),
  );
}

void main() {
  group('WithdrawController', () {
    late FakePixApi pixApi;
    late FakeAuthApi authApi;
    late WithdrawController controller;

    setUp(() {
      pixApi = FakePixApi();
      authApi = FakeAuthApi();
      controller = WithdrawController(
        pixApi: pixApi,
        authApi: authApi,
        statusPollInterval: const Duration(milliseconds: 10),
        maxPollAttempts: 20,
      );
    });

    tearDown(() {
      controller.dispose();
    });

    test('loadProfile populates the already-registered Pix key', () async {
      authApi.pixKeyToReturn = 'user@example.com';

      await controller.loadProfile();

      expect(controller.loadingProfile, isFalse);
      expect(controller.registeredPixKey, 'user@example.com');
    });

    test('loadProfile leaves registeredPixKey null when the user has none yet', () async {
      await controller.loadProfile();

      expect(controller.registeredPixKey, isNull);
    });

    test('submit moves straight to done when Efi confirms paid immediately', () async {
      pixApi.withdrawResult = _withdrawal(status: 'paid');

      await controller.submit(amount: 10, pixKey: 'user@example.com');

      expect(controller.stage, WithdrawStage.done);
      expect(controller.withdrawal?.status, 'paid');
      expect(pixApi.lastAmount, 10);
      expect(pixApi.lastPixKey, 'user@example.com');
      expect(pixApi.lastIdempotencyKey, isNotEmpty);
    });

    test('submit moves to processing and polls until the backend confirms paid', () async {
      pixApi.withdrawResult = _withdrawal(status: 'processing');
      pixApi.listWithdrawalsQueue = [
        [_withdrawal(status: 'processing')],
        [_withdrawal(status: 'processing')],
        [_withdrawal(status: 'paid')],
      ];

      await controller.submit(amount: 10, pixKey: 'user@example.com');
      expect(controller.stage, WithdrawStage.processing);

      await _waitUntil(() => controller.stage == WithdrawStage.done);
      expect(controller.withdrawal?.status, 'paid');
    });

    test('submit moves to processing and polls until the backend confirms failed', () async {
      pixApi.withdrawResult = _withdrawal(status: 'processing');
      pixApi.listWithdrawalsQueue = [
        [_withdrawal(status: 'processing')],
        [_withdrawal(status: 'failed')],
      ];

      await controller.submit(amount: 10, pixKey: 'user@example.com');
      await _waitUntil(() => controller.stage == WithdrawStage.done);

      expect(controller.withdrawal?.status, 'failed');
    });

    test('submit surfaces a friendly message for insufficient balance (400)', () async {
      pixApi.throwOnWithdraw = const ApiException(statusCode: 400, message: 'insufficient balance');

      await controller.submit(amount: 999, pixKey: 'user@example.com');

      expect(controller.stage, WithdrawStage.error);
      expect(controller.errorMessage, contains('Saldo insuficiente'));
    });

    test('submit surfaces a friendly message for a missing/invalid pix_key (400)', () async {
      pixApi.throwOnWithdraw = const ApiException(
        statusCode: 400,
        message: 'no pix_key provided or registered for this user',
      );

      await controller.submit(amount: 10);

      expect(controller.stage, WithdrawStage.error);
      expect(controller.errorMessage, contains('chave Pix'));
    });

    test('submit surfaces a friendly message when the rate limit is hit (429)', () async {
      pixApi.throwOnWithdraw = const ApiException(statusCode: 429, message: '5 per 1 hour');

      await controller.submit(amount: 10, pixKey: 'user@example.com');

      expect(controller.stage, WithdrawStage.error);
      expect(controller.errorMessage, contains('Limite'));
    });

    test('submit surfaces a non-ApiException failure without crashing', () async {
      pixApi.throwOnWithdraw = Exception('timeout');

      await controller.submit(amount: 10, pixKey: 'user@example.com');

      expect(controller.stage, WithdrawStage.error);
      expect(controller.errorMessage, isNotNull);
    });

    test('resetToForm clears error and withdrawal state, stops polling', () async {
      pixApi.withdrawResult = _withdrawal(status: 'processing');
      pixApi.listWithdrawalsQueue = [
        [_withdrawal(status: 'processing')],
      ];

      await controller.submit(amount: 10, pixKey: 'user@example.com');
      expect(controller.stage, WithdrawStage.processing);

      controller.resetToForm();

      expect(controller.stage, WithdrawStage.form);
      expect(controller.withdrawal, isNull);
      expect(controller.errorMessage, isNull);
    });
  });
}

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api_exception.dart';
import '../models/withdrawal.dart';
import '../services/auth_api.dart';
import '../services/pix_api.dart';

enum WithdrawStage { form, submitting, processing, done, error }

/// Orquestra o formulário de saque Pix: carrega a chave Pix já cadastrada
/// no perfil (via AuthApi.login(), que devolve o usuário atual sem criar
/// nada), envia POST /pix/withdraw com uma Idempotency-Key nova, e depois
/// consulta GET /pix/withdrawals periodicamente até o status sair de
/// "processing"/"pending" (confirmado via webhook ou reconciliação do
/// backend) -- nunca assume o resultado sozinho, só reflete o que o
/// backend confirmar.
class WithdrawController extends ChangeNotifier {
  WithdrawController({
    required this.pixApi,
    required this.authApi,
    this.statusPollInterval = const Duration(seconds: 5),
    this.maxPollAttempts = 24,
  });

  final PixApi pixApi;
  final AuthApi authApi;
  final Duration statusPollInterval;
  final int maxPollAttempts;

  WithdrawStage stage = WithdrawStage.form;
  bool loadingProfile = true;
  String? registeredPixKey;
  String? errorMessage;
  Withdrawal? withdrawal;

  Timer? _pollTimer;
  int _pollAttempts = 0;

  static const _terminalStatuses = {'paid', 'failed'};

  Future<void> loadProfile() async {
    loadingProfile = true;
    notifyListeners();
    try {
      final user = await authApi.login();
      registeredPixKey = user.pixKey;
    } on ApiException catch (e) {
      errorMessage = e.message;
    } catch (_) {
      errorMessage = 'Não foi possível carregar seu perfil.';
    }
    loadingProfile = false;
    notifyListeners();
  }

  Future<void> submit({required double amount, String? pixKey}) async {
    stage = WithdrawStage.submitting;
    errorMessage = null;
    notifyListeners();

    // O backend não guarda a Idempotency-Key associada a uma "tentativa de
    // formulário" -- é só a chave real de deduplicação da Efí (ver
    // create_withdrawal no backend), então uma chave nova a cada submit
    // explícito do usuário é o comportamento certo (igual ao mesmo padrão
    // já usado em MiningController.collect).
    final idempotencyKey = 'withdraw-${DateTime.now().microsecondsSinceEpoch}';

    try {
      final result = await pixApi.withdraw(
        amount: amount,
        pixKey: pixKey,
        idempotencyKey: idempotencyKey,
      );
      withdrawal = result;
      if (_terminalStatuses.contains(result.status)) {
        stage = WithdrawStage.done;
      } else {
        stage = WithdrawStage.processing;
        _pollStatus();
      }
      notifyListeners();
    } on ApiException catch (e) {
      stage = WithdrawStage.error;
      errorMessage = _friendlyError(e);
      notifyListeners();
    } catch (_) {
      stage = WithdrawStage.error;
      errorMessage = 'Não foi possível solicitar o saque. Tente novamente.';
      notifyListeners();
    }
  }

  void _pollStatus() {
    _pollTimer?.cancel();
    _pollAttempts = 0;
    _pollTimer = Timer.periodic(statusPollInterval, (timer) async {
      _pollAttempts++;
      final current = withdrawal;
      if (current == null) {
        timer.cancel();
        return;
      }
      try {
        final all = await pixApi.listWithdrawals();
        Withdrawal? updated;
        for (final w in all) {
          if (w.id == current.id) {
            updated = w;
            break;
          }
        }
        if (updated != null) {
          withdrawal = updated;
          if (_terminalStatuses.contains(updated.status)) {
            timer.cancel();
            stage = WithdrawStage.done;
          }
          notifyListeners();
        }
      } catch (_) {
        // Falha transitória de rede durante o polling -- não interrompe o
        // usuário nem muda de estágio, só tenta de novo no próximo tick.
      }
      if (_pollAttempts >= maxPollAttempts) {
        timer.cancel();
      }
    });
  }

  static String _friendlyError(ApiException e) {
    if (e.statusCode == 429) {
      return 'Limite de solicitações de saque atingido (5 por hora). Tente novamente mais tarde.';
    }
    if (e.statusCode == 400) {
      final message = e.message.toLowerCase();
      if (message.contains('insufficient balance')) {
        return 'Saldo insuficiente para este valor.';
      }
      if (message.contains('pix_key')) {
        return 'Informe uma chave Pix válida para receber o saque.';
      }
    }
    return e.message;
  }

  void resetToForm() {
    _pollTimer?.cancel();
    stage = WithdrawStage.form;
    errorMessage = null;
    withdrawal = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }
}

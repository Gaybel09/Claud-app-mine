import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api_exception.dart';
import '../models/cube.dart';
import '../models/mining_session.dart';
import '../services/ads_api.dart';
import '../services/cubes_api.dart';
import '../services/mining_api.dart';

enum CubeCycleStage {
  idle,
  watchingAd,
  waitingAdConfirmation,
  mining,
  readyToCollect,
  collecting,
  collected,
  error,
}

/// Orquestra o ciclo do cubo (seção 7): assistir anúncio -> aguardar o
/// callback assíncrono do SDK confirmar -> iniciar mineração -> aguardar
/// ends_at -> coletar. Não faz nenhuma suposição de status local: o "pronto
/// para coletar" só é aceito quando o backend confirma via GET
/// /mining/status, nunca por cálculo otimista do relógio do aparelho.
class MiningController extends ChangeNotifier {
  MiningController({
    required this.cubesApi,
    required this.adsApi,
    required this.miningApi,
    this.adConfirmationPollInterval = const Duration(seconds: 2),
    this.miningStatusPollInterval = const Duration(seconds: 5),
    this.maxAdConfirmationAttempts = 30,
  });

  final CubesApi cubesApi;
  final AdsApi adsApi;
  final MiningApi miningApi;
  final Duration adConfirmationPollInterval;
  final Duration miningStatusPollInterval;
  final int maxAdConfirmationAttempts;

  CubeCycleStage stage = CubeCycleStage.idle;
  Cube? cube;
  MiningSession? session;
  MiningStatus? status;
  double? lastRewardAmount;
  String? errorMessage;

  Timer? _pollTimer;
  int _adConfirmationAttempts = 0;

  Future<void> loadCube() async {
    try {
      final cubes = await cubesApi.listMyCubes();
      cube = cubes.isNotEmpty ? cubes.first : null;
    } on ApiException catch (e) {
      errorMessage = e.message;
    }
    notifyListeners();
  }

  Future<void> watchAd() async {
    final currentCube = cube;
    if (currentCube == null) return;

    stage = CubeCycleStage.watchingAd;
    errorMessage = null;
    notifyListeners();

    try {
      // TODO: plugar aqui a exibição real do SDK de anúncio (AdMob etc.);
      // por enquanto o backend simula a confirmação via callback SSV.
      final adView = await adsApi.watch(adNetwork: 'generic_ssv');
      stage = CubeCycleStage.waitingAdConfirmation;
      notifyListeners();

      _adConfirmationAttempts = 0;
      _pollForAdConfirmation(currentCube.id, adView.id);
    } on ApiException catch (e) {
      stage = CubeCycleStage.error;
      errorMessage = e.message;
      notifyListeners();
    }
  }

  void _pollForAdConfirmation(int cubeId, int adViewId) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(adConfirmationPollInterval, (timer) async {
      _adConfirmationAttempts++;
      try {
        final started = await miningApi.start(cubeId: cubeId, adViewId: adViewId);
        timer.cancel();
        session = started;
        stage = CubeCycleStage.mining;
        notifyListeners();
        _pollMiningStatus();
      } on ApiException catch (e) {
        final adNotYetConfirmed = e.statusCode == 400;
        final gaveUp = _adConfirmationAttempts >= maxAdConfirmationAttempts;
        if (!adNotYetConfirmed || gaveUp) {
          timer.cancel();
          stage = CubeCycleStage.error;
          errorMessage = adNotYetConfirmed
              ? 'A confirmação do anúncio demorou demais. Tente assistir de novo.'
              : e.message;
          notifyListeners();
        }
        // Senão: o callback do SDK ainda não confirmou -- continua tentando.
      }
    });
  }

  void _pollMiningStatus() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(miningStatusPollInterval, (timer) async {
      final currentSession = session;
      if (currentSession == null) return;
      try {
        final result = await miningApi.status(sessionId: currentSession.id);
        status = result;
        if (result.readyToCollect) {
          timer.cancel();
          stage = CubeCycleStage.readyToCollect;
        }
        notifyListeners();
      } on ApiException catch (e) {
        timer.cancel();
        stage = CubeCycleStage.error;
        errorMessage = e.message;
        notifyListeners();
      }
    });
  }

  Future<void> collect() async {
    final currentSession = session;
    if (currentSession == null) return;

    stage = CubeCycleStage.collecting;
    errorMessage = null;
    notifyListeners();

    // O backend não guarda a Idempotency-Key (mining_sessions não tem essa
    // coluna) -- a proteção real contra duplicidade é o lock de linha e o
    // status da sessão, então uma chave nova a cada tentativa explícita do
    // usuário não compromete a idempotência (ver módulo mining no backend).
    final idempotencyKey = 'collect-${currentSession.id}-${DateTime.now().microsecondsSinceEpoch}';

    try {
      final result = await miningApi.collect(
        sessionId: currentSession.id,
        idempotencyKey: idempotencyKey,
      );
      lastRewardAmount = result.rewardAmount;
      stage = CubeCycleStage.collected;
      session = null;
      status = null;
      notifyListeners();
    } on ApiException catch (e) {
      stage = CubeCycleStage.error;
      errorMessage = e.message;
      notifyListeners();
    }
  }

  /// Volta pro estado inicial para um novo ciclo (novo anúncio, nova sessão).
  void resetToIdle() {
    _pollTimer?.cancel();
    stage = CubeCycleStage.idle;
    lastRewardAmount = null;
    errorMessage = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }
}

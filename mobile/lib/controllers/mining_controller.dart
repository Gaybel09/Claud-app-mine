import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api_exception.dart';
import '../models/cube.dart';
import '../models/mining_session.dart';
import '../services/ads_api.dart';
import '../services/cubes_api.dart';
import '../services/mining_api.dart';
import '../services/rewarded_ad_service.dart';

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

/// Estado de UI de um bônus opcional (Cubo Épico / Acelerar) -- separado do
/// CubeCycleStage principal porque a mineração continua rodando em paralelo
/// (o timer não pausa) enquanto o usuário assiste o anúncio bônus; uma
/// falha aqui não deve derrubar a tela toda pro estado de erro genérico.
enum BonusActionStage { idle, watchingAd, waitingConfirmation, error }

enum _BonusKind { epic, speedup }

/// Orquestra o ciclo do cubo (seção 7): assistir o RewardedAd (Google
/// Mobile Ads) até o fim -> registrar e confirmar o ad_view no backend ->
/// aguardar a confirmação liberar POST /mining/start -> aguardar ends_at ->
/// coletar. Não faz nenhuma suposição de status local: o "pronto para
/// coletar" só é aceito quando o backend confirma via GET /mining/status,
/// nunca por cálculo otimista do relógio do aparelho.
class MiningController extends ChangeNotifier {
  MiningController({
    required this.cubesApi,
    required this.adsApi,
    required this.miningApi,
    required this.rewardedAdService,
    this.adConfirmationPollInterval = const Duration(seconds: 2),
    this.miningStatusPollInterval = const Duration(seconds: 5),
    this.maxAdConfirmationAttempts = 30,
  });

  final CubesApi cubesApi;
  final AdsApi adsApi;
  final MiningApi miningApi;
  final RewardedAdService rewardedAdService;
  final Duration adConfirmationPollInterval;
  final Duration miningStatusPollInterval;
  final int maxAdConfirmationAttempts;

  CubeCycleStage stage = CubeCycleStage.idle;
  Cube? cube;
  MiningSession? session;
  MiningStatus? status;
  double? lastRewardAmount;
  String? errorMessage;

  BonusActionStage epicBonusStage = BonusActionStage.idle;
  String? epicBonusError;
  BonusActionStage speedupStage = BonusActionStage.idle;
  String? speedupError;

  Timer? _pollTimer;
  int _adConfirmationAttempts = 0;
  Timer? _epicBonusPollTimer;
  Timer? _speedupPollTimer;

  Future<void> loadCube() async {
    try {
      final cubes = await cubesApi.listMyCubes();
      cube = cubes.isNotEmpty ? cubes.first : null;
    } on ApiException catch (e) {
      // Antes desta correção, uma falha aqui só setava errorMessage sem
      // nunca sair de "stage == idle" -- como a tela mostra um spinner
      // enquanto cube == null e stage != error, a UI ficava carregando
      // pra sempre (nunca chegava a mostrar o erro nem o botão de tentar
      // de novo). Ver também ApiClient.requestTimeout: sem timeout, a
      // própria chamada podia nunca resolver.
      errorMessage = e.message;
      stage = CubeCycleStage.error;
      notifyListeners();
      return;
    } catch (_) {
      errorMessage = 'Não foi possível carregar seu cubo. Tente novamente.';
      stage = CubeCycleStage.error;
      notifyListeners();
      return;
    }

    final currentCube = cube;
    if (currentCube == null) {
      notifyListeners();
      return;
    }

    // Seção 7 -- restaura o estado de uma mineração já em andamento (ex: o
    // usuário trocou de aba e voltou, o que recria este controller do zero
    // -- ver mobile/lib/screens/cube/cube_screen.dart). Sem isso, a tela
    // sempre voltava a mostrar "ASSISTIR ANÚNCIO" mesmo com uma sessão
    // RUNNING de verdade no backend -- e, antes da correção em
    // start_mining_session (backend), isso permitia iniciar uma segunda
    // sessão em cima da primeira.
    try {
      final active = await miningApi.activeSession(cubeId: currentCube.id);
      if (active != null) {
        session = active;
        final result = await miningApi.status(sessionId: active.id);
        status = result;
        if (result.readyToCollect) {
          stage = CubeCycleStage.readyToCollect;
        } else {
          stage = CubeCycleStage.mining;
          _pollMiningStatus();
        }
      }
    } on ApiException catch (e) {
      errorMessage = e.message;
      stage = CubeCycleStage.error;
    } catch (_) {
      errorMessage = 'Não foi possível verificar sua mineração em andamento. Tente novamente.';
      stage = CubeCycleStage.error;
    }
    notifyListeners();
  }

  Future<void> watchAd() async {
    final currentCube = cube;
    if (currentCube == null) return;

    stage = CubeCycleStage.watchingAd;
    errorMessage = null;
    notifyListeners();

    // RewardedAd real (google_mobile_ads) -- só retorna true quando o
    // usuário assistiu até o fim de verdade (onUserEarnedReward do SDK do
    // Google disparou). Antes disso, nada abaixo roda: o botão "ASSISTIR
    // ANÚNCIO" não inicia a mineração sem o anúncio ter sido concluído.
    final earnedReward = await rewardedAdService.loadAndShow();
    if (!earnedReward) {
      stage = CubeCycleStage.error;
      errorMessage = 'Assista o anúncio até o fim para começar a minerar.';
      notifyListeners();
      return;
    }

    try {
      final adView = await adsApi.watch(adNetwork: 'admob_rewarded');

      // ATENÇÃO -- CONFIRMAÇÃO TEMPORÁRIA VIA CLIENTE (ver docstring de
      // AdsApi.confirm): o app assistiu o anúncio até o fim de verdade,
      // mas quem confirma o ad_view pro backend ainda é o próprio app, não
      // a verificação servidor-a-servidor (SSV) real do Google. Remova
      // esta chamada quando o SSV real estiver implementado -- o polling
      // logo abaixo já está pronto pra esperar uma confirmação que chegue
      // de forma assíncrona/externa, como vai acontecer com SSV de verdade.
      await adsApi.confirm(adViewId: adView.id, userId: currentCube.userId);

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

  /// Cubo Épico -- assistir um segundo RewardedAd enquanto a mineração roda
  /// pra essa sessão pagar +25% na coleta (ver backend POST
  /// /mining/epic-bonus). Só 1x por sessão -- ver
  /// MiningSession.epicBonusApplied.
  Future<void> useEpicBonus() => _startBonusFlow(_BonusKind.epic);

  /// Acelerar -- assistir um RewardedAd enquanto a mineração roda pra
  /// reduzir o tempo restante pela metade (ver backend POST
  /// /mining/speedup). Só 1x por sessão -- ver MiningSession.speedupUsed.
  Future<void> useSpeedup() => _startBonusFlow(_BonusKind.speedup);

  Future<void> _startBonusFlow(_BonusKind kind) async {
    final currentSession = session;
    if (currentSession == null) return;
    if (kind == _BonusKind.epic && currentSession.epicBonusApplied) return;
    if (kind == _BonusKind.speedup && currentSession.speedupUsed) return;

    _setBonusStage(kind, BonusActionStage.watchingAd, error: null);

    final earnedReward = await rewardedAdService.loadAndShow();
    if (!earnedReward) {
      _setBonusStage(
        kind,
        BonusActionStage.error,
        error: 'Assista o anúncio até o fim para usar este bônus.',
      );
      return;
    }

    try {
      final adView = await adsApi.watch(adNetwork: 'admob_rewarded');

      // Mesma confirmação temporária via cliente que watchAd() usa -- ver
      // docstring de AdsApi.confirm.
      await adsApi.confirm(adViewId: adView.id, userId: currentSession.userId);

      _setBonusStage(kind, BonusActionStage.waitingConfirmation, error: null);
      _pollForBonus(
        kind: kind,
        apply: () => kind == _BonusKind.epic
            ? miningApi.applyEpicBonus(sessionId: currentSession.id, adViewId: adView.id)
            : miningApi.applySpeedup(sessionId: currentSession.id, adViewId: adView.id),
      );
    } on ApiException catch (e) {
      _setBonusStage(kind, BonusActionStage.error, error: e.message);
    }
  }

  void _pollForBonus({
    required _BonusKind kind,
    required Future<MiningSession> Function() apply,
  }) {
    (kind == _BonusKind.epic ? _epicBonusPollTimer : _speedupPollTimer)?.cancel();

    int attempts = 0;
    late Timer timer;
    timer = Timer.periodic(adConfirmationPollInterval, (t) async {
      attempts++;
      try {
        final updated = await apply();
        t.cancel();
        session = updated;
        _setBonusStage(kind, BonusActionStage.idle, error: null);
      } on ApiException catch (e) {
        final adNotYetConfirmed = e.statusCode == 400;
        final gaveUp = attempts >= maxAdConfirmationAttempts;
        if (!adNotYetConfirmed || gaveUp) {
          t.cancel();
          _setBonusStage(
            kind,
            BonusActionStage.error,
            error: adNotYetConfirmed
                ? 'A confirmação do anúncio demorou demais. Tente de novo.'
                : e.message,
          );
        }
        // Senão: o callback do SDK ainda não confirmou -- continua tentando.
      }
    });

    if (kind == _BonusKind.epic) {
      _epicBonusPollTimer = timer;
    } else {
      _speedupPollTimer = timer;
    }
  }

  void _setBonusStage(_BonusKind kind, BonusActionStage newStage, {required String? error}) {
    if (kind == _BonusKind.epic) {
      epicBonusStage = newStage;
      epicBonusError = error;
    } else {
      speedupStage = newStage;
      speedupError = error;
    }
    notifyListeners();
  }

  /// Volta pro estado inicial para um novo ciclo (novo anúncio, nova sessão).
  void resetToIdle() {
    _pollTimer?.cancel();
    _epicBonusPollTimer?.cancel();
    _speedupPollTimer?.cancel();
    stage = CubeCycleStage.idle;
    lastRewardAmount = null;
    errorMessage = null;
    epicBonusStage = BonusActionStage.idle;
    epicBonusError = null;
    speedupStage = BonusActionStage.idle;
    speedupError = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _epicBonusPollTimer?.cancel();
    _speedupPollTimer?.cancel();
    super.dispose();
  }
}

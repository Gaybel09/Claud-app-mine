import 'package:cubemine_pix/controllers/mining_controller.dart';
import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/models/cube.dart';
import 'package:cubemine_pix/models/mining_session.dart';
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

void main() {
  group('MiningController', () {
    late FakeCubesApi cubesApi;
    late FakeAdsApi adsApi;
    late FakeMiningApi miningApi;
    late FakeRewardedAdService rewardedAdService;
    late MiningController controller;

    setUp(() {
      cubesApi = FakeCubesApi()
        ..cubes = [
          Cube(
            id: 1,
            userId: 1,
            type: 'comum',
            speed: 1.0,
            bonusChance: 0.05,
            acquiredAt: DateTime.now(),
          ),
        ];
      adsApi = FakeAdsApi();
      miningApi = FakeMiningApi();
      rewardedAdService = FakeRewardedAdService();
      controller = MiningController(
        cubesApi: cubesApi,
        adsApi: adsApi,
        miningApi: miningApi,
        rewardedAdService: rewardedAdService,
        adConfirmationPollInterval: const Duration(milliseconds: 10),
        miningStatusPollInterval: const Duration(milliseconds: 10),
        maxAdConfirmationAttempts: 5,
      );
    });

    tearDown(() {
      controller.dispose();
    });

    test('loadCube populates cube from the API', () async {
      await controller.loadCube();
      expect(controller.cube?.id, 1);
    });

    test('loadCube moves to the error stage when listMyCubes fails (never gets stuck loading)', () async {
      cubesApi.throwOnList = const ApiException(statusCode: 401, message: 'User not registered');

      await controller.loadCube();

      // Antes da correção, um erro aqui só setava errorMessage sem nunca
      // sair de stage == idle -- como a tela mostra um spinner enquanto
      // cube == null e stage != error, isso ficava carregando pra sempre.
      expect(controller.stage, CubeCycleStage.error);
      expect(controller.errorMessage, 'User not registered');
    });

    test('loadCube moves to the error stage on a non-ApiException failure (e.g. a timeout)', () async {
      cubesApi.throwOnList = Exception('timeout');

      await controller.loadCube();

      expect(controller.stage, CubeCycleStage.error);
      expect(controller.errorMessage, isNotNull);
    });

    test('loadCube stays idle when there is no active mining session for the cube', () async {
      miningApi.activeSessionToReturn = null;

      await controller.loadCube();

      expect(controller.stage, CubeCycleStage.idle);
      expect(controller.session, isNull);
      expect(miningApi.activeSessionCallCount, 1);
    });

    test('loadCube restores the mining stage when an active session already exists', () async {
      // Reproduz o cenário reportado: o usuário trocou de aba e voltou (o
      // que recria o MiningController do zero), mas já existe uma sessão
      // RUNNING de verdade no backend -- a tela deve voltar mostrando o
      // cronômetro, não o botão "ASSISTIR ANÚNCIO".
      final startedAt = DateTime.now().subtract(const Duration(minutes: 10));
      miningApi.activeSessionToReturn = MiningSession(
        id: 99,
        userId: 1,
        cubeId: 1,
        adViewId: 5,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );
      miningApi.statusNotReadyCount = 999;

      await controller.loadCube();

      expect(controller.stage, CubeCycleStage.mining);
      expect(controller.session?.id, 99);
      // watchAd/mining.start nunca são chamados de novo -- a sessão
      // existente é só descoberta e restaurada, não recriada.
      expect(miningApi.startCallCount, 0);
    });

    test('loadCube restores the readyToCollect stage when the active session already matured', () async {
      final startedAt = DateTime.now().subtract(const Duration(hours: 3));
      miningApi.activeSessionToReturn = MiningSession(
        id: 100,
        userId: 1,
        cubeId: 1,
        adViewId: 6,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );
      miningApi.statusNotReadyCount = 0; // status já vem ready_to_collect=true

      await controller.loadCube();

      expect(controller.stage, CubeCycleStage.readyToCollect);
      expect(controller.session?.id, 100);
    });

    test('watchAd retries mining/start until the ad is confirmed, then moves to mining', () async {
      await controller.loadCube();
      miningApi.startFailuresBeforeSuccess = 2;
      final startedAt = DateTime.now();
      miningApi.sessionToReturn = MiningSession(
        id: 42,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );

      await controller.watchAd();
      expect(controller.stage, CubeCycleStage.waitingAdConfirmation);

      await _waitUntil(() => controller.stage == CubeCycleStage.mining);

      expect(controller.session?.id, 42);
      // 2 tentativas rejeitadas (ad ainda não confirmado) + 1 que teve sucesso.
      expect(miningApi.startCallCount, 3);
    });

    test('watchAd shows the RewardedAd and only confirms the ad_view after the reward is earned', () async {
      await controller.loadCube();
      final startedAt = DateTime.now();
      miningApi.sessionToReturn = MiningSession(
        id: 1,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );

      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.mining);

      expect(rewardedAdService.loadAndShowCallCount, 1);
      expect(adsApi.confirmCallCount, 1);
      expect(adsApi.lastConfirmedAdViewId, 1);
      // O user_id vem do cube carregado, não de uma fonte separada.
      expect(adsApi.lastConfirmedUserId, cubesApi.cubes.first.userId);
    });

    test('watchAd never starts mining when the user does not watch the ad to the end', () async {
      await controller.loadCube();
      rewardedAdService.earnedReward = false;

      await controller.watchAd();

      expect(controller.stage, CubeCycleStage.error);
      expect(controller.errorMessage, contains('até o fim'));
      // Nada do fluxo de confirmação/mineração pode ter rodado -- é
      // exatamente a garantia de que o botão não libera a mineração sem
      // onUserEarnedReward ter disparado de verdade.
      expect(adsApi.confirmCallCount, 0);
      expect(miningApi.startCallCount, 0);
    });

    test('gives up waiting for ad confirmation after the max attempts', () async {
      await controller.loadCube();
      miningApi.startFailuresBeforeSuccess = 999; // nunca confirma

      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.error);

      expect(controller.errorMessage, contains('demorou demais'));
    });

    test('surfaces a non-400 error from mining/start immediately, without retrying', () async {
      await controller.loadCube();
      miningApi.throwOnStart = const ApiException(statusCode: 404, message: 'cube not found');

      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.error);

      expect(controller.errorMessage, 'cube not found');
      expect(miningApi.startCallCount, 1);
    });

    test('polls mining status until ready, then collect() succeeds', () async {
      await controller.loadCube();
      final startedAt = DateTime.now();
      miningApi.sessionToReturn = MiningSession(
        id: 7,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );
      miningApi.statusNotReadyCount = 2;
      miningApi.collectResult = const MiningCollectResult(
        sessionId: 7,
        status: 'collected',
        rewardAmount: 0.55,
      );

      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.readyToCollect);

      await controller.collect();
      expect(controller.stage, CubeCycleStage.collected);
      expect(controller.lastRewardAmount, 0.55);
      expect(controller.session, isNull);
    });

    test('surfaces a collect error (e.g. insufficient reward fund) without crashing', () async {
      await controller.loadCube();
      final startedAt = DateTime.now();
      miningApi.sessionToReturn = MiningSession(
        id: 9,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );
      miningApi.throwOnCollect = const ApiException(
        statusCode: 503,
        message: 'reward fund unavailable, try again later',
      );

      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.readyToCollect);

      await controller.collect();
      expect(controller.stage, CubeCycleStage.error);
      expect(controller.errorMessage, contains('reward fund'));
    });

    test('resetToIdle clears session and error state for a new cycle', () async {
      await controller.loadCube();
      miningApi.throwOnStart = const ApiException(statusCode: 400, message: 'ad_view is not confirmed');

      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.error);

      controller.resetToIdle();
      expect(controller.stage, CubeCycleStage.idle);
      expect(controller.session, isNull);
      expect(controller.errorMessage, isNull);
    });

    Future<void> startMiningFor(MiningController controller) async {
      await controller.loadCube();
      final startedAt = DateTime.now();
      miningApi.sessionToReturn = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: false,
      );
      // Nunca reporta ready_to_collect -- sem isso, o poll de status
      // (miningStatusPollInterval, 10ms neste teste) reportaria pronto na
      // primeira checagem (statusNotReadyCount default é 0) e a sessão
      // sairia do estágio "mining" antes das asserções dos testes de bônus.
      miningApi.statusNotReadyCount = 999;
      await controller.watchAd();
      await _waitUntil(() => controller.stage == CubeCycleStage.mining);
    }

    test('useEpicBonus watches an ad and applies the bonus to the session', () async {
      await startMiningFor(controller);
      final updated = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: controller.session!.startedAt,
        endsAt: controller.session!.endsAt,
        status: 'running',
        epicBonusApplied: true,
        epicBonusVideosWatched: 2,
        speedupUsed: false,
      );
      miningApi.epicBonusResult = updated;

      await controller.useEpicBonus();
      await _waitUntil(() => controller.epicBonusStage == BonusActionStage.idle);

      expect(controller.session!.epicBonusApplied, isTrue);
      expect(miningApi.epicBonusCallCount, 1);
      expect(miningApi.lastEpicBonusSessionId, 55);
      expect(rewardedAdService.loadAndShowCallCount, 2); // 1 pra iniciar + 1 pro bônus
    });

    test('useEpicBonus reflects progress (1/2) without applying after only one video', () async {
      await startMiningFor(controller);
      final updated = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: controller.session!.startedAt,
        endsAt: controller.session!.endsAt,
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 1,
        speedupUsed: false,
      );
      miningApi.epicBonusResult = updated;

      await controller.useEpicBonus();
      await _waitUntil(() => controller.epicBonusStage == BonusActionStage.idle);

      expect(controller.session!.epicBonusVideosWatched, 1);
      expect(controller.session!.epicBonusApplied, isFalse);

      // Não é o "já aplicado" que bloqueia uma segunda chamada -- com só 1
      // vídeo assistido, tocar de novo deve chamar a API normalmente pro
      // segundo vídeo.
      await controller.useEpicBonus();
      await _waitUntil(() => miningApi.epicBonusCallCount >= 2);
      expect(miningApi.epicBonusCallCount, 2);
    });

    test('useEpicBonus does not call the API when the ad is not watched to the end', () async {
      await startMiningFor(controller);
      rewardedAdService.earnedReward = false;

      await controller.useEpicBonus();

      expect(controller.epicBonusStage, BonusActionStage.error);
      expect(controller.epicBonusError, contains('até o fim'));
      expect(miningApi.epicBonusCallCount, 0);
    });

    test('useEpicBonus does nothing when the bonus was already applied', () async {
      await startMiningFor(controller);
      controller.session = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: controller.session!.startedAt,
        endsAt: controller.session!.endsAt,
        status: 'running',
        epicBonusApplied: true,
        epicBonusVideosWatched: 2,
        speedupUsed: false,
      );

      await controller.useEpicBonus();

      expect(rewardedAdService.loadAndShowCallCount, 1); // só o do início da mineração
      expect(miningApi.epicBonusCallCount, 0);
    });

    test('useEpicBonus surfaces a 409 (already used) without disrupting the mining stage', () async {
      await startMiningFor(controller);
      miningApi.throwOnEpicBonus = const ApiException(
        statusCode: 409,
        message: 'epic bonus already used for this session',
      );

      await controller.useEpicBonus();
      await _waitUntil(() => controller.epicBonusStage == BonusActionStage.error);

      expect(controller.epicBonusError, contains('already used'));
      // A mineração em si continua rodando normalmente -- um erro no bônus
      // não derruba a tela toda pro estado de erro genérico.
      expect(controller.stage, CubeCycleStage.mining);
    });

    test('useSpeedup watches an ad and reduces the remaining time', () async {
      await startMiningFor(controller);
      final updated = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: controller.session!.startedAt,
        endsAt: DateTime.now().add(const Duration(minutes: 30)),
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: true,
      );
      miningApi.speedupResult = updated;

      await controller.useSpeedup();
      await _waitUntil(() => controller.speedupStage == BonusActionStage.idle);

      expect(controller.session!.speedupUsed, isTrue);
      expect(miningApi.speedupCallCount, 1);
    });

    test('useSpeedup does nothing when speedup was already used', () async {
      await startMiningFor(controller);
      controller.session = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: controller.session!.startedAt,
        endsAt: controller.session!.endsAt,
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: true,
      );

      await controller.useSpeedup();

      expect(miningApi.speedupCallCount, 0);
    });

    test('useSpeedup retries while the ad_view is not confirmed yet, then succeeds', () async {
      await startMiningFor(controller);
      miningApi.speedupFailuresBeforeSuccess = 2;
      miningApi.speedupResult = MiningSession(
        id: 55,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: controller.session!.startedAt,
        endsAt: controller.session!.endsAt,
        status: 'running',
        epicBonusApplied: false,
        epicBonusVideosWatched: 0,
        speedupUsed: true,
      );

      await controller.useSpeedup();
      await _waitUntil(() => controller.speedupStage == BonusActionStage.idle);

      expect(controller.session!.speedupUsed, isTrue);
      // 2 tentativas rejeitadas (ad ainda não confirmado) + 1 que teve sucesso.
      expect(miningApi.speedupCallCount, 3);
    });

    test('useSpeedup gives up after the max polling attempts', () async {
      await startMiningFor(controller);
      miningApi.speedupFailuresBeforeSuccess = 999; // nunca confirma

      await controller.useSpeedup();
      await _waitUntil(() => controller.speedupStage == BonusActionStage.error);

      expect(controller.speedupError, contains('demorou demais'));
      expect(controller.stage, CubeCycleStage.mining);
    });
  });
}

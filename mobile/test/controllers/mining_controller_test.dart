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
      controller = MiningController(
        cubesApi: cubesApi,
        adsApi: adsApi,
        miningApi: miningApi,
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
      );

      await controller.watchAd();
      expect(controller.stage, CubeCycleStage.waitingAdConfirmation);

      await _waitUntil(() => controller.stage == CubeCycleStage.mining);

      expect(controller.session?.id, 42);
      // 2 tentativas rejeitadas (ad ainda não confirmado) + 1 que teve sucesso.
      expect(miningApi.startCallCount, 3);
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
  });
}

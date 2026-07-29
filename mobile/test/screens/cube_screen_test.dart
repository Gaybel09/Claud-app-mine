import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/models/cube.dart';
import 'package:cubemine_pix/models/mining_session.dart';
import 'package:cubemine_pix/screens/cube/cube_screen.dart';
import 'package:cubemine_pix/services/ads_api.dart';
import 'package:cubemine_pix/services/cubes_api.dart';
import 'package:cubemine_pix/services/mining_api.dart';
import 'package:cubemine_pix/services/rewarded_ad_service.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

void main() {
  group('CubeScreen', () {
    testWidgets('runs the full watch ad -> mining -> ready -> collect cycle', (tester) async {
      final cubesApi = FakeCubesApi()
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
      final adsApi = FakeAdsApi();
      final miningApi = FakeMiningApi();
      final startedAt = DateTime.now();
      miningApi.sessionToReturn = MiningSession(
        id: 5,
        userId: 1,
        cubeId: 1,
        adViewId: 1,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        speedupUsed: false,
      );
      miningApi.statusNotReadyCount = 1;
      miningApi.collectResult = const MiningCollectResult(
        sessionId: 5,
        status: 'collected',
        rewardAmount: 0.42,
      );

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            Provider<CubesApi>.value(value: cubesApi),
            Provider<AdsApi>.value(value: adsApi),
            Provider<MiningApi>.value(value: miningApi),
            Provider<RewardedAdService>.value(value: FakeRewardedAdService()),
          ],
          child: MaterialApp(
            theme: AppTheme.dark,
            home: const CubeScreen(
              adConfirmationPollInterval: Duration(milliseconds: 10),
              miningStatusPollInterval: Duration(milliseconds: 10),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('watch_ad_button')), findsOneWidget);

      await tester.tap(find.byKey(const Key('watch_ad_button')));
      await tester.pump();

      // Aguarda o(s) poll(s) de confirmação do anúncio e de status da
      // mineração resolverem, avançando o relógio em pequenos incrementos
      // (não dá pra usar pumpAndSettle com um Timer.periodic ainda ativo).
      for (var i = 0; i < 20; i++) {
        await tester.pump(const Duration(milliseconds: 20));
      }

      expect(find.byKey(const Key('collect_button')), findsOneWidget);

      await tester.tap(find.byKey(const Key('collect_button')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 20));

      expect(find.byKey(const Key('reward_amount_text')), findsOneWidget);
      expect(find.text('Você ganhou R\$ 0.42!'), findsOneWidget);
    });

    testWidgets('shows an error and lets the user retry when the ad is never confirmed', (tester) async {
      final cubesApi = FakeCubesApi()
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
      final adsApi = FakeAdsApi();
      final miningApi = FakeMiningApi()..startFailuresBeforeSuccess = 999;

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            Provider<CubesApi>.value(value: cubesApi),
            Provider<AdsApi>.value(value: adsApi),
            Provider<MiningApi>.value(value: miningApi),
            Provider<RewardedAdService>.value(value: FakeRewardedAdService()),
          ],
          child: MaterialApp(
            theme: AppTheme.dark,
            home: const CubeScreen(
              adConfirmationPollInterval: Duration(milliseconds: 5),
              miningStatusPollInterval: Duration(milliseconds: 5),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('watch_ad_button')));
      await tester.pump();

      for (var i = 0; i < 30; i++) {
        await tester.pump(const Duration(milliseconds: 10));
      }

      expect(find.byKey(const Key('cube_error_text')), findsOneWidget);

      await tester.tap(find.text('TENTAR DE NOVO'));
      await tester.pump();

      expect(find.byKey(const Key('watch_ad_button')), findsOneWidget);
    });

    testWidgets(
        'shows the mining countdown (not the watch-ad button) when a CubeScreen recreated from '
        'scratch finds an active session already running on the backend', (tester) async {
      // Reproduz o bug reportado: trocar de aba e voltar recria o
      // CubeScreen (e o MiningController) do zero -- ver
      // mobile/lib/screens/home/home_shell.dart. Sem restaurar o estado a
      // partir do backend, a tela voltaria mostrando "ASSISTIR ANÚNCIO"
      // mesmo com uma mineração de verdade em andamento.
      final cubesApi = FakeCubesApi()
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
      final adsApi = FakeAdsApi();
      final miningApi = FakeMiningApi();
      final startedAt = DateTime.now().subtract(const Duration(minutes: 10));
      miningApi.activeSessionToReturn = MiningSession(
        id: 77,
        userId: 1,
        cubeId: 1,
        adViewId: 3,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: false,
        speedupUsed: false,
      );
      miningApi.statusNotReadyCount = 999;

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            Provider<CubesApi>.value(value: cubesApi),
            Provider<AdsApi>.value(value: adsApi),
            Provider<MiningApi>.value(value: miningApi),
            Provider<RewardedAdService>.value(value: FakeRewardedAdService()),
          ],
          child: MaterialApp(
            theme: AppTheme.dark,
            home: const CubeScreen(
              adConfirmationPollInterval: Duration(milliseconds: 10),
              miningStatusPollInterval: Duration(milliseconds: 10),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('watch_ad_button')), findsNothing);
      // Não iniciou (nem podia) uma sessão nova -- só descobriu e restaurou
      // a que já existia.
      expect(miningApi.startCallCount, 0);
      expect(adsApi.confirmCallCount, 0);
    });

    testWidgets('does not unlock mining when the RewardedAd is closed before the reward is earned', (tester) async {
      final cubesApi = FakeCubesApi()
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
      final adsApi = FakeAdsApi();
      final miningApi = FakeMiningApi();
      final rewardedAdService = FakeRewardedAdService()..earnedReward = false;

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            Provider<CubesApi>.value(value: cubesApi),
            Provider<AdsApi>.value(value: adsApi),
            Provider<MiningApi>.value(value: miningApi),
            Provider<RewardedAdService>.value(value: rewardedAdService),
          ],
          child: MaterialApp(theme: AppTheme.dark, home: const CubeScreen()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('watch_ad_button')));
      await tester.pumpAndSettle();

      // O anúncio foi "fechado" sem disparar onUserEarnedReward -- nem
      // /ads/watch nem /mining/start podem ter sido chamados.
      expect(adsApi.confirmCallCount, 0);
      expect(miningApi.startCallCount, 0);
      expect(find.byKey(const Key('cube_error_text')), findsOneWidget);
      expect(find.text('Assista o anúncio até o fim para começar a minerar.'), findsOneWidget);
    });

    Future<FakeMiningApi> pumpRunningMiningScreen(
      WidgetTester tester, {
      bool epicBonusApplied = false,
      bool speedupUsed = false,
    }) async {
      final cubesApi = FakeCubesApi()
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
      final adsApi = FakeAdsApi();
      final miningApi = FakeMiningApi();
      final startedAt = DateTime.now();
      miningApi.activeSessionToReturn = MiningSession(
        id: 88,
        userId: 1,
        cubeId: 1,
        adViewId: 3,
        startedAt: startedAt,
        endsAt: startedAt.add(const Duration(hours: 2)),
        status: 'running',
        epicBonusApplied: epicBonusApplied,
        speedupUsed: speedupUsed,
      );
      miningApi.statusNotReadyCount = 999;

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            Provider<CubesApi>.value(value: cubesApi),
            Provider<AdsApi>.value(value: adsApi),
            Provider<MiningApi>.value(value: miningApi),
            Provider<RewardedAdService>.value(value: FakeRewardedAdService()),
          ],
          child: MaterialApp(
            theme: AppTheme.dark,
            home: const CubeScreen(
              adConfirmationPollInterval: Duration(milliseconds: 10),
              miningStatusPollInterval: Duration(milliseconds: 10),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      return miningApi;
    }

    testWidgets('shows both bonus buttons while mining and neither has been used', (tester) async {
      await pumpRunningMiningScreen(tester);

      expect(find.byKey(const Key('epic_bonus_button')), findsOneWidget);
      expect(find.byKey(const Key('speedup_button')), findsOneWidget);
    });

    testWidgets('hides a bonus button that was already used when the session is restored', (tester) async {
      await pumpRunningMiningScreen(tester, epicBonusApplied: true, speedupUsed: true);

      expect(find.byKey(const Key('epic_bonus_button')), findsNothing);
      expect(find.byKey(const Key('speedup_button')), findsNothing);
    });

    testWidgets('tapping the epic bonus button watches an ad and hides the button once applied', (tester) async {
      final miningApi = await pumpRunningMiningScreen(tester);
      miningApi.epicBonusResult = MiningSession(
        id: 88,
        userId: 1,
        cubeId: 1,
        adViewId: 3,
        startedAt: miningApi.activeSessionToReturn!.startedAt,
        endsAt: miningApi.activeSessionToReturn!.endsAt,
        status: 'running',
        epicBonusApplied: true,
        speedupUsed: false,
      );

      await tester.tap(find.byKey(const Key('epic_bonus_button')));
      await tester.pump();
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 20));
      }

      expect(miningApi.epicBonusCallCount, 1);
      expect(find.byKey(const Key('epic_bonus_button')), findsNothing);
      // O botão de acelerar continua disponível -- são bônus independentes.
      expect(find.byKey(const Key('speedup_button')), findsOneWidget);
    });

    testWidgets('tapping the speedup button watches an ad and hides the button once used', (tester) async {
      final miningApi = await pumpRunningMiningScreen(tester);
      miningApi.speedupResult = MiningSession(
        id: 88,
        userId: 1,
        cubeId: 1,
        adViewId: 3,
        startedAt: miningApi.activeSessionToReturn!.startedAt,
        endsAt: DateTime.now().add(const Duration(minutes: 30)),
        status: 'running',
        epicBonusApplied: false,
        speedupUsed: true,
      );

      await tester.tap(find.byKey(const Key('speedup_button')));
      await tester.pump();
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 20));
      }

      expect(miningApi.speedupCallCount, 1);
      expect(find.byKey(const Key('speedup_button')), findsNothing);
      expect(find.byKey(const Key('epic_bonus_button')), findsOneWidget);
    });

    testWidgets('shows a friendly error under the epic bonus button without leaving the mining stage', (tester) async {
      final miningApi = await pumpRunningMiningScreen(tester);
      miningApi.throwOnEpicBonus = const ApiException(
        statusCode: 409,
        message: 'epic bonus already used for this session',
      );

      await tester.tap(find.byKey(const Key('epic_bonus_button')));
      await tester.pump();
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 20));
      }

      expect(find.textContaining('epic bonus already used'), findsOneWidget);
      // A mineração em si segue rodando -- o botão continua visível pra
      // tentar de novo, a tela não vira o estado de erro genérico.
      expect(find.byKey(const Key('epic_bonus_button')), findsOneWidget);
      expect(find.byKey(const Key('cube_error_text')), findsNothing);
    });
  });
}

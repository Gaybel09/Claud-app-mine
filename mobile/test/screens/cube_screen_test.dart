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
  });
}

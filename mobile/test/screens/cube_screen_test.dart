import 'package:cubemine_pix/models/cube.dart';
import 'package:cubemine_pix/models/mining_session.dart';
import 'package:cubemine_pix/screens/cube/cube_screen.dart';
import 'package:cubemine_pix/services/ads_api.dart';
import 'package:cubemine_pix/services/cubes_api.dart';
import 'package:cubemine_pix/services/mining_api.dart';
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
  });
}

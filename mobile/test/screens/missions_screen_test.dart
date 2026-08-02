import 'package:cubemine_pix/models/weekly_mission.dart';
import 'package:cubemine_pix/screens/missions/missions_screen.dart';
import 'package:cubemine_pix/services/missions_api.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

Widget _wrap({required FakeMissionsApi missionsApi}) {
  return MultiProvider(
    providers: [Provider<MissionsApi>.value(value: missionsApi)],
    child: MaterialApp(theme: AppTheme.dark, home: const Scaffold(body: MissionsScreen())),
  );
}

void main() {
  group('MissionsScreen', () {
    testWidgets('shows progress toward the weekly target', (tester) async {
      final missionsApi = FakeMissionsApi()
        ..resultToReturn = WeeklyMission(
          target: 10,
          progress: 4,
          completed: false,
          weekStart: DateTime.now(),
          weekEnd: DateTime.now().add(const Duration(days: 7)),
          multiplier: 1.5,
          multiplierActive: false,
          multiplierExpiresAt: null,
        );

      // Não usa pumpAndSettle(): MissionsScreen mantém um Timer.periodic
      // rodando pra atualizar a contagem regressiva do multiplicador
      // (ver _MissionsScreenState), que nunca "settles" sozinho -- dois
      // pumps bastam pra resolver o FutureBuilder (1º builda o frame de
      // loading, 2º processa o Future já resolvido e reconstrói com os
      // dados).
      await tester.pumpWidget(_wrap(missionsApi: missionsApi));
      await tester.pump();
      await tester.pump();

      expect(find.text('4/10 coletas'), findsOneWidget);
      expect(find.byKey(const Key('multiplier_active_card')), findsNothing);
    });

    testWidgets('shows the completed state without the multiplier card once it has expired', (tester) async {
      final missionsApi = FakeMissionsApi()
        ..resultToReturn = WeeklyMission(
          target: 10,
          progress: 10,
          completed: true,
          weekStart: DateTime.now(),
          weekEnd: DateTime.now().add(const Duration(days: 7)),
          multiplier: 1.5,
          multiplierActive: false,
          multiplierExpiresAt: DateTime.now().subtract(const Duration(hours: 1)),
        );

      await tester.pumpWidget(_wrap(missionsApi: missionsApi));
      await tester.pump();
      await tester.pump();

      expect(find.text('10/10 coletas'), findsOneWidget);
      expect(find.byKey(const Key('multiplier_active_card')), findsNothing);
    });

    testWidgets('shows the multiplier card with a countdown while active', (tester) async {
      final missionsApi = FakeMissionsApi()
        ..resultToReturn = WeeklyMission(
          target: 10,
          progress: 10,
          completed: true,
          weekStart: DateTime.now(),
          weekEnd: DateTime.now().add(const Duration(days: 7)),
          multiplier: 1.5,
          multiplierActive: true,
          multiplierExpiresAt: DateTime.now().add(const Duration(hours: 2, minutes: 30)),
        );

      await tester.pumpWidget(_wrap(missionsApi: missionsApi));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(const Key('multiplier_active_card')), findsOneWidget);
      expect(find.text('Multiplicador 1.5x ativo!'), findsOneWidget);
      expect(find.byKey(const Key('multiplier_countdown_text')), findsOneWidget);
    });

    testWidgets('shows an error message when the mission call fails', (tester) async {
      final missionsApi = FakeMissionsApi()..throwOnGetWeeklyMission = Exception('network error');

      await tester.pumpWidget(_wrap(missionsApi: missionsApi));
      await tester.pump();
      await tester.pump();

      expect(find.text('Não foi possível carregar a missão semanal.'), findsOneWidget);
    });
  });
}

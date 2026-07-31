import 'package:cubemine_pix/models/ranking.dart';
import 'package:cubemine_pix/screens/ranking/ranking_screen.dart';
import 'package:cubemine_pix/services/auth_api.dart';
import 'package:cubemine_pix/services/ranking_api.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

Widget _wrap({required FakeRankingApi rankingApi, FakeAuthApi? authApi}) {
  return MultiProvider(
    providers: [
      Provider<RankingApi>.value(value: rankingApi),
      Provider<AuthApi>.value(value: authApi ?? FakeAuthApi()),
    ],
    child: MaterialApp(theme: AppTheme.dark, home: const Scaffold(body: RankingScreen())),
  );
}

void main() {
  group('RankingScreen', () {
    testWidgets('shows the general top 10 with the current user highlighted', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(
            top: [
              RankingEntry(rank: 1, userId: 5, displayName: 'Top Minerador', total: 42.0),
              RankingEntry(rank: 2, userId: 1, displayName: 'Minerador #1', total: 30.0),
            ],
            myRank: 2,
            myTotal: 30.0,
          ),
          regional: null,
        );

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.text('Top Minerador'), findsOneWidget);
      expect(find.text('Minerador #1'), findsOneWidget);
      expect(find.text('R\$ 42.00'), findsOneWidget);
      expect(find.byKey(const Key('ranking_my_position_tile')), findsOneWidget);
    });

    testWidgets('shows a separate "my position" tile when the user is outside the top 10', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(
            top: [RankingEntry(rank: 1, userId: 5, displayName: 'Top Minerador', total: 42.0)],
            myRank: 47,
            myTotal: 1.0,
          ),
          regional: null,
        );

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('ranking_my_position_tile')), findsOneWidget);
      expect(find.text('Você'), findsOneWidget);
    });

    testWidgets('shows a message instead of a rank when the user has not scored yet', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(top: [], myRank: null, myTotal: 0),
          regional: null,
        );

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('ranking_no_score_text')), findsOneWidget);
      expect(find.byKey(const Key('ranking_my_position_tile')), findsNothing);
    });

    testWidgets('hides the scope toggle when there is no regional ranking', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(top: [], myRank: null, myTotal: 0),
          regional: null,
        );

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('ranking_scope_regional_chip')), findsNothing);
    });

    testWidgets('toggling to the regional scope shows the regional top list', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(
            top: [RankingEntry(rank: 1, userId: 1, displayName: 'Geral #1', total: 10.0)],
            myRank: 1,
            myTotal: 10.0,
          ),
          regional: RegionalScopeRanking(
            top: [RankingEntry(rank: 1, userId: 1, displayName: 'Regional #1', total: 10.0)],
            myRank: 1,
            myTotal: 10.0,
            regionCode: 'BR-SP',
            regionLabel: 'São Paulo',
          ),
        );

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.text('Geral #1'), findsOneWidget);
      expect(find.text('Regional #1'), findsNothing);

      await tester.tap(find.byKey(const Key('ranking_scope_regional_chip')));
      await tester.pumpAndSettle();

      expect(find.text('Regional #1'), findsOneWidget);
      expect(find.text('Geral #1'), findsNothing);
      expect(find.text('São Paulo'), findsWidgets);
    });

    testWidgets('shows the "define a nickname" prompt when the user has none', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(top: [], myRank: null, myTotal: 0),
          regional: null,
        );

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('nickname_display_text')), findsOneWidget);
      expect(find.text('Defina um apelido'), findsOneWidget);
    });

    testWidgets('shows the current nickname when already set', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(top: [], myRank: null, myTotal: 0),
          regional: null,
        );
      final authApi = FakeAuthApi()..nicknameToReturn = 'Foguete Roxo';

      await tester.pumpWidget(_wrap(rankingApi: rankingApi, authApi: authApi));
      await tester.pumpAndSettle();

      expect(find.text('Foguete Roxo'), findsOneWidget);
    });

    testWidgets('editing the nickname calls updateNickname and reloads', (tester) async {
      final rankingApi = FakeRankingApi()
        ..resultToReturn = const RankingResult(
          general: ScopeRanking(top: [], myRank: null, myTotal: 0),
          regional: null,
        );
      final authApi = FakeAuthApi();

      await tester.pumpWidget(_wrap(rankingApi: rankingApi, authApi: authApi));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('edit_nickname_button')));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('nickname_input')), 'Novo Apelido');
      await tester.tap(find.byKey(const Key('nickname_save_button')));
      await tester.pumpAndSettle();

      expect(authApi.updateNicknameCallCount, 1);
      expect(authApi.lastUpdatedNickname, 'Novo Apelido');
      expect(find.text('Novo Apelido'), findsOneWidget);
    });

    testWidgets('shows an error message when the ranking call fails', (tester) async {
      final rankingApi = FakeRankingApi()..throwOnGetRanking = Exception('network error');

      await tester.pumpWidget(_wrap(rankingApi: rankingApi));
      await tester.pumpAndSettle();

      expect(find.text('Não foi possível carregar o ranking.'), findsOneWidget);
    });
  });
}

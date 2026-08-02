class RankingEntry {
  const RankingEntry({
    required this.rank,
    required this.userId,
    required this.displayName,
    required this.total,
  });

  final int rank;
  final int userId;
  final String displayName;
  final double total;

  factory RankingEntry.fromJson(Map<String, dynamic> json) {
    return RankingEntry(
      rank: json['rank'] as int,
      userId: json['user_id'] as int,
      displayName: json['display_name'] as String,
      total: double.parse(json['total'].toString()),
    );
  }
}

class ScopeRanking {
  const ScopeRanking({required this.top, required this.myRank, required this.myTotal});

  final List<RankingEntry> top;
  final int? myRank;
  final double myTotal;

  factory ScopeRanking.fromJson(Map<String, dynamic> json) {
    return ScopeRanking(
      top: (json['top'] as List).map((e) => RankingEntry.fromJson(e as Map<String, dynamic>)).toList(),
      myRank: json['my_rank'] as int?,
      myTotal: double.parse(json['my_total'].toString()),
    );
  }
}

class RegionalScopeRanking extends ScopeRanking {
  const RegionalScopeRanking({
    required super.top,
    required super.myRank,
    required super.myTotal,
    required this.regionCode,
    required this.regionLabel,
  });

  final String regionCode;
  final String regionLabel;

  factory RegionalScopeRanking.fromJson(Map<String, dynamic> json) {
    final scope = ScopeRanking.fromJson(json);
    return RegionalScopeRanking(
      top: scope.top,
      myRank: scope.myRank,
      myTotal: scope.myTotal,
      regionCode: json['region_code'] as String,
      regionLabel: json['region_label'] as String,
    );
  }
}

class LevelRankingEntry {
  const LevelRankingEntry({
    required this.rank,
    required this.userId,
    required this.displayName,
    required this.level,
    required this.xp,
  });

  final int rank;
  final int userId;
  final String displayName;
  final int level;
  final int xp;

  factory LevelRankingEntry.fromJson(Map<String, dynamic> json) {
    return LevelRankingEntry(
      rank: json['rank'] as int,
      userId: json['user_id'] as int,
      displayName: json['display_name'] as String,
      level: json['level'] as int,
      xp: json['xp'] as int,
    );
  }
}

class LevelScopeRanking {
  const LevelScopeRanking({
    required this.top,
    required this.myRank,
    required this.myLevel,
    required this.myXp,
  });

  final List<LevelRankingEntry> top;
  final int? myRank;
  final int myLevel;
  final int myXp;

  factory LevelScopeRanking.fromJson(Map<String, dynamic> json) {
    return LevelScopeRanking(
      top: (json['top'] as List).map((e) => LevelRankingEntry.fromJson(e as Map<String, dynamic>)).toList(),
      myRank: json['my_rank'] as int?,
      myLevel: json['my_level'] as int,
      myXp: json['my_xp'] as int,
    );
  }
}

class RankingResult {
  const RankingResult({required this.general, required this.regional, required this.byLevel});

  final ScopeRanking general;

  /// null quando o usuário ainda não tem país/estado detectado (ver
  /// User.countryCode/stateCode) -- a tela mostra só o ranking geral nesse
  /// caso.
  final RegionalScopeRanking? regional;

  /// Ranking por nível/XP (seção "Níveis") -- nunca null, já que todo
  /// usuário tem um nível (começa no 1 com 0 XP).
  final LevelScopeRanking byLevel;

  factory RankingResult.fromJson(Map<String, dynamic> json) {
    return RankingResult(
      general: ScopeRanking.fromJson(json['general'] as Map<String, dynamic>),
      regional: json['regional'] == null
          ? null
          : RegionalScopeRanking.fromJson(json['regional'] as Map<String, dynamic>),
      byLevel: LevelScopeRanking.fromJson(json['by_level'] as Map<String, dynamic>),
    );
  }
}

class LevelStatus {
  const LevelStatus({
    required this.level,
    required this.xp,
    required this.xpIntoLevel,
    required this.xpForNextLevel,
  });

  final int level;
  final int xp;

  /// XP já acumulado dentro do nível atual (0 logo que sobe de nível).
  final int xpIntoLevel;

  /// XP total necessário pra sair deste nível pro próximo -- xpIntoLevel /
  /// xpForNextLevel é a fração da barra de progresso.
  final int xpForNextLevel;

  factory LevelStatus.fromJson(Map<String, dynamic> json) {
    return LevelStatus(
      level: json['level'] as int,
      xp: json['xp'] as int,
      xpIntoLevel: json['xp_into_level'] as int,
      xpForNextLevel: json['xp_for_next_level'] as int,
    );
  }
}

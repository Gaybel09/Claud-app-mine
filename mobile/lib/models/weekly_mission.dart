class WeeklyMission {
  const WeeklyMission({
    required this.target,
    required this.progress,
    required this.completed,
    required this.weekStart,
    required this.weekEnd,
    required this.multiplier,
    required this.multiplierActive,
    required this.multiplierExpiresAt,
  });

  final int target;
  final int progress;
  final bool completed;
  final DateTime weekStart;
  final DateTime weekEnd;
  final double multiplier;
  final bool multiplierActive;

  /// null quando o multiplicador nunca foi ativado (ou já expirou) --
  /// enquanto multiplierActive for true, é o instante em que ele deixa de
  /// valer (ver GET /missions/weekly).
  final DateTime? multiplierExpiresAt;

  factory WeeklyMission.fromJson(Map<String, dynamic> json) {
    return WeeklyMission(
      target: json['target'] as int,
      progress: json['progress'] as int,
      completed: json['completed'] as bool,
      weekStart: DateTime.parse(json['week_start'] as String),
      weekEnd: DateTime.parse(json['week_end'] as String),
      multiplier: double.parse(json['multiplier'].toString()),
      multiplierActive: json['multiplier_active'] as bool,
      multiplierExpiresAt: json['multiplier_expires_at'] == null
          ? null
          : DateTime.parse(json['multiplier_expires_at'] as String),
    );
  }
}

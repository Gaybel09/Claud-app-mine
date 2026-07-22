class Cube {
  const Cube({
    required this.id,
    required this.userId,
    required this.type,
    required this.speed,
    required this.bonusChance,
    required this.acquiredAt,
  });

  final int id;
  final int userId;
  final String type;
  final double speed;
  final double bonusChance;
  final DateTime acquiredAt;

  factory Cube.fromJson(Map<String, dynamic> json) {
    return Cube(
      id: json['id'] as int,
      userId: json['user_id'] as int,
      type: json['type'] as String,
      speed: double.parse(json['speed'].toString()),
      bonusChance: double.parse(json['bonus_chance'].toString()),
      acquiredAt: DateTime.parse(json['acquired_at'] as String),
    );
  }
}

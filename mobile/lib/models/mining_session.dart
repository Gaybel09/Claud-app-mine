class MiningSession {
  const MiningSession({
    required this.id,
    required this.userId,
    required this.cubeId,
    required this.adViewId,
    required this.startedAt,
    required this.endsAt,
    required this.status,
  });

  final int id;
  final int userId;
  final int cubeId;
  final int adViewId;
  final DateTime startedAt;
  final DateTime endsAt;
  final String status;

  factory MiningSession.fromJson(Map<String, dynamic> json) {
    return MiningSession(
      id: json['id'] as int,
      userId: json['user_id'] as int,
      cubeId: json['cube_id'] as int,
      adViewId: json['ad_view_id'] as int,
      startedAt: DateTime.parse(json['started_at'] as String),
      endsAt: DateTime.parse(json['ends_at'] as String),
      status: json['status'] as String,
    );
  }
}

class MiningStatus {
  const MiningStatus({
    required this.id,
    required this.status,
    required this.endsAt,
    required this.readyToCollect,
  });

  final int id;
  final String status;
  final DateTime endsAt;
  final bool readyToCollect;

  factory MiningStatus.fromJson(Map<String, dynamic> json) {
    return MiningStatus(
      id: json['id'] as int,
      status: json['status'] as String,
      endsAt: DateTime.parse(json['ends_at'] as String),
      readyToCollect: json['ready_to_collect'] as bool,
    );
  }
}

class MiningCollectResult {
  const MiningCollectResult({
    required this.sessionId,
    required this.status,
    required this.rewardAmount,
  });

  final int sessionId;
  final String status;
  final double rewardAmount;

  factory MiningCollectResult.fromJson(Map<String, dynamic> json) {
    return MiningCollectResult(
      sessionId: json['session_id'] as int,
      status: json['status'] as String,
      rewardAmount: double.parse(json['reward_amount'].toString()),
    );
  }
}

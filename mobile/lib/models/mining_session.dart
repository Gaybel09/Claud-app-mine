/// Quantos vídeos o fluxo de desbloqueio do Cubo Épico exige -- ver
/// EPIC_BONUS_VIDEOS_REQUIRED no backend (app/modules/mining/service.py).
const epicBonusVideosRequired = 2;

class MiningSession {
  const MiningSession({
    required this.id,
    required this.userId,
    required this.cubeId,
    required this.adViewId,
    required this.startedAt,
    required this.endsAt,
    required this.status,
    required this.epicBonusApplied,
    required this.epicBonusVideosWatched,
    required this.speedupUsed,
  });

  final int id;
  final int userId;
  final int cubeId;
  final int adViewId;
  final DateTime startedAt;
  final DateTime endsAt;
  final String status;
  // Cubo Épico -- fluxo de desbloqueio: exige epicBonusVideosRequired (2)
  // vídeos distintos assistidos (epicBonusVideosWatched conta o progresso,
  // 0/1/2) antes de epicBonusApplied virar true e a sessão passar a pagar
  // +25% na coleta. Acelerar (speedupUsed) reduz o tempo restante pela
  // metade -- só 1 vídeo, sem fluxo de progresso. Ambos só podem ser
  // usados 1x por sessão; a tela do cubo esconde o botão/painel
  // correspondente assim que o respectivo campo indica "completo".
  final bool epicBonusApplied;
  final int epicBonusVideosWatched;
  final bool speedupUsed;

  factory MiningSession.fromJson(Map<String, dynamic> json) {
    return MiningSession(
      id: json['id'] as int,
      userId: json['user_id'] as int,
      cubeId: json['cube_id'] as int,
      adViewId: json['ad_view_id'] as int,
      startedAt: DateTime.parse(json['started_at'] as String),
      endsAt: DateTime.parse(json['ends_at'] as String),
      status: json['status'] as String,
      epicBonusApplied: json['epic_bonus_applied'] as bool,
      epicBonusVideosWatched: json['epic_bonus_videos_watched'] as int,
      speedupUsed: json['speedup_used'] as bool,
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

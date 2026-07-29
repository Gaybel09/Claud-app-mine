import '../core/api_client.dart';
import '../models/mining_session.dart';

abstract class MiningApi {
  Future<MiningSession> start({required int cubeId, required int adViewId});

  /// Sessão RUNNING atual para o cubo, se houver -- usada ao carregar a
  /// tela do cubo para restaurar o estado (cronômetro, "pronto para
  /// coletar") em vez de sempre assumir idle. `null` quando não há nenhuma
  /// sessão ativa (não é erro).
  Future<MiningSession?> activeSession({required int cubeId});

  Future<MiningStatus> status({required int sessionId});

  Future<MiningCollectResult> collect({
    required int sessionId,
    required String idempotencyKey,
  });

  /// Cubo Épico -- assistir um segundo RewardedAd enquanto a mineração
  /// roda pra essa sessão pagar +25% na coleta. Só 1x por sessão (ver
  /// MiningSession.epicBonusApplied).
  Future<MiningSession> applyEpicBonus({required int sessionId, required int adViewId});

  /// Acelerar -- assistir um RewardedAd enquanto a mineração roda pra
  /// reduzir o tempo restante pela metade. Só 1x por sessão (ver
  /// MiningSession.speedupUsed).
  Future<MiningSession> applySpeedup({required int sessionId, required int adViewId});
}

class HttpMiningApi implements MiningApi {
  HttpMiningApi(this._client);

  final ApiClient _client;

  @override
  Future<MiningSession> start({required int cubeId, required int adViewId}) async {
    final data = await _client.post('/mining/start', body: {
      'cube_id': cubeId,
      'ad_view_id': adViewId,
    });
    return MiningSession.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<MiningSession?> activeSession({required int cubeId}) async {
    final data = await _client.get(
      '/mining/active-session',
      query: {'cube_id': cubeId.toString()},
    );
    if (data == null) return null;
    return MiningSession.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<MiningStatus> status({required int sessionId}) async {
    final data = await _client.get(
      '/mining/status',
      query: {'session_id': sessionId.toString()},
    );
    return MiningStatus.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<MiningCollectResult> collect({
    required int sessionId,
    required String idempotencyKey,
  }) async {
    final data = await _client.post(
      '/mining/collect',
      body: {'session_id': sessionId},
      extraHeaders: {'Idempotency-Key': idempotencyKey},
    );
    return MiningCollectResult.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<MiningSession> applyEpicBonus({required int sessionId, required int adViewId}) async {
    final data = await _client.post('/mining/epic-bonus', body: {
      'session_id': sessionId,
      'ad_view_id': adViewId,
    });
    return MiningSession.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<MiningSession> applySpeedup({required int sessionId, required int adViewId}) async {
    final data = await _client.post('/mining/speedup', body: {
      'session_id': sessionId,
      'ad_view_id': adViewId,
    });
    return MiningSession.fromJson(data as Map<String, dynamic>);
  }
}

import '../core/api_client.dart';
import '../models/mining_session.dart';

abstract class MiningApi {
  Future<MiningSession> start({required int cubeId, required int adViewId});

  Future<MiningStatus> status({required int sessionId});

  Future<MiningCollectResult> collect({
    required int sessionId,
    required String idempotencyKey,
  });
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
}

import '../core/api_client.dart';
import '../models/level_status.dart';

abstract class LevelsApi {
  Future<LevelStatus> getMyLevel();
}

class HttpLevelsApi implements LevelsApi {
  HttpLevelsApi(this._client);

  final ApiClient _client;

  @override
  Future<LevelStatus> getMyLevel() async {
    final data = await _client.get('/levels/me');
    return LevelStatus.fromJson(data as Map<String, dynamic>);
  }
}

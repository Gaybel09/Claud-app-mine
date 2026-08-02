import '../core/api_client.dart';
import '../models/weekly_mission.dart';

abstract class MissionsApi {
  Future<WeeklyMission> getWeeklyMission();
}

class HttpMissionsApi implements MissionsApi {
  HttpMissionsApi(this._client);

  final ApiClient _client;

  @override
  Future<WeeklyMission> getWeeklyMission() async {
    final data = await _client.get('/missions/weekly');
    return WeeklyMission.fromJson(data as Map<String, dynamic>);
  }
}

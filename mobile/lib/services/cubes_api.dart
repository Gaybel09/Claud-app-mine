import '../core/api_client.dart';
import '../models/cube.dart';

abstract class CubesApi {
  Future<List<Cube>> listMyCubes();
}

class HttpCubesApi implements CubesApi {
  HttpCubesApi(this._client);

  final ApiClient _client;

  @override
  Future<List<Cube>> listMyCubes() async {
    final data = await _client.get('/cubes/me');
    return (data as List)
        .map((e) => Cube.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}

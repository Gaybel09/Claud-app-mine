import '../core/api_client.dart';
import '../models/app_user.dart';

abstract class AuthApi {
  Future<AppUser> register({String? phone, String? pixKey});
  Future<AppUser> login();
  Future<AppUser> updateNickname(String nickname);
}

class HttpAuthApi implements AuthApi {
  HttpAuthApi(this._client);

  final ApiClient _client;

  @override
  Future<AppUser> register({String? phone, String? pixKey}) async {
    final data = await _client.post('/auth/register', body: {
      'phone': ?phone,
      'pix_key': ?pixKey,
    });
    return AppUser.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<AppUser> login() async {
    final data = await _client.post('/auth/login');
    return AppUser.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<AppUser> updateNickname(String nickname) async {
    final data = await _client.patch('/auth/nickname', body: {'nickname': nickname});
    return AppUser.fromJson(data as Map<String, dynamic>);
  }
}

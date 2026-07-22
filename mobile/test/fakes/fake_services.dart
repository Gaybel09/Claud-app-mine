import 'dart:async';

import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/core/auth_service.dart';
import 'package:cubemine_pix/models/ad_view.dart';
import 'package:cubemine_pix/models/app_user.dart';
import 'package:cubemine_pix/models/cube.dart';
import 'package:cubemine_pix/models/ledger_entry.dart';
import 'package:cubemine_pix/models/mining_session.dart';
import 'package:cubemine_pix/services/ads_api.dart';
import 'package:cubemine_pix/services/auth_api.dart';
import 'package:cubemine_pix/services/cubes_api.dart';
import 'package:cubemine_pix/services/mining_api.dart';
import 'package:cubemine_pix/services/wallet_api.dart';

AppUser fakeAppUser({String email = 'user@example.com'}) => AppUser(
      id: 1,
      email: email,
      phone: null,
      pixKey: null,
      kycStatus: 'pending',
      createdAt: DateTime.now(),
      isBlocked: false,
    );

class FakeAuthService implements AuthService {
  final _controller = StreamController<AppAuthUser?>.broadcast();
  AppAuthUser? _current;

  Object? throwOnSignIn;
  Object? throwOnRegister;

  @override
  Stream<AppAuthUser?> authStateChanges() => _controller.stream;

  @override
  AppAuthUser? get currentUser => _current;

  @override
  Future<AppAuthUser> registerWithEmailPassword(String email, String password) async {
    if (throwOnRegister != null) throw throwOnRegister!;
    final user = AppAuthUser(uid: 'uid-$email', email: email);
    _current = user;
    _controller.add(user);
    return user;
  }

  @override
  Future<AppAuthUser> signInWithEmailPassword(String email, String password) async {
    if (throwOnSignIn != null) throw throwOnSignIn!;
    final user = AppAuthUser(uid: 'uid-$email', email: email);
    _current = user;
    _controller.add(user);
    return user;
  }

  @override
  Future<String?> getIdToken({bool forceRefresh = false}) async => 'fake-id-token';

  @override
  Future<void> signOut() async {
    _current = null;
    _controller.add(null);
  }

  void dispose() => _controller.close();
}

class FakeAuthApi implements AuthApi {
  bool loginCalled = false;
  bool registerCalled = false;
  String? registeredPhone;
  Object? throwOnLogin;
  Object? throwOnRegister;

  @override
  Future<AppUser> login() async {
    loginCalled = true;
    if (throwOnLogin != null) throw throwOnLogin!;
    return fakeAppUser();
  }

  @override
  Future<AppUser> register({String? phone, String? pixKey}) async {
    registerCalled = true;
    registeredPhone = phone;
    if (throwOnRegister != null) throw throwOnRegister!;
    return fakeAppUser();
  }
}

class FakeCubesApi implements CubesApi {
  List<Cube> cubes = const [];
  Object? throwOnList;

  @override
  Future<List<Cube>> listMyCubes() async {
    if (throwOnList != null) throw throwOnList!;
    return cubes;
  }
}

class FakeAdsApi implements AdsApi {
  int nextAdViewId = 1;
  Object? throwOnWatch;

  @override
  Future<AdView> watch({required String adNetwork}) async {
    if (throwOnWatch != null) throw throwOnWatch!;
    return AdView(id: nextAdViewId, status: 'pending');
  }
}

/// Fake controlável do módulo mining: [startFailuresBeforeSuccess] simula o
/// backend rejeitando /mining/start (400) enquanto o callback do SDK de
/// anúncio ainda não confirmou; [statusNotReadyCount] simula chamadas de
/// GET /mining/status antes de ready_to_collect virar true.
class FakeMiningApi implements MiningApi {
  int startCallCount = 0;
  int startFailuresBeforeSuccess = 0;
  MiningSession? sessionToReturn;
  Object? throwOnStart;

  int statusCallCount = 0;
  int statusNotReadyCount = 0;

  MiningCollectResult? collectResult;
  Object? throwOnCollect;

  @override
  Future<MiningSession> start({required int cubeId, required int adViewId}) async {
    startCallCount++;
    if (throwOnStart != null) throw throwOnStart!;
    if (startCallCount <= startFailuresBeforeSuccess) {
      throw const ApiException(statusCode: 400, message: 'ad_view is not confirmed');
    }
    return sessionToReturn!;
  }

  @override
  Future<MiningStatus> status({required int sessionId}) async {
    statusCallCount++;
    final ready = statusCallCount > statusNotReadyCount;
    return MiningStatus(
      id: sessionId,
      status: 'running',
      endsAt: sessionToReturn?.endsAt ?? DateTime.now(),
      readyToCollect: ready,
    );
  }

  @override
  Future<MiningCollectResult> collect({
    required int sessionId,
    required String idempotencyKey,
  }) async {
    if (throwOnCollect != null) throw throwOnCollect!;
    return collectResult!;
  }
}

class FakeWalletApi implements WalletApi {
  double balance = 0;
  Statement? statement;
  Object? throwOnBalance;
  Object? throwOnStatement;

  @override
  Future<double> getBalance() async {
    if (throwOnBalance != null) throw throwOnBalance!;
    return balance;
  }

  @override
  Future<Statement> getStatement({int page = 1, int pageSize = 20}) async {
    if (throwOnStatement != null) throw throwOnStatement!;
    return statement ?? const Statement(items: [], page: 1, pageSize: 20, total: 0);
  }
}

import 'dart:async';

import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/core/auth_service.dart';
import 'package:cubemine_pix/models/ad_view.dart';
import 'package:cubemine_pix/models/app_user.dart';
import 'package:cubemine_pix/models/cube.dart';
import 'package:cubemine_pix/models/ledger_entry.dart';
import 'package:cubemine_pix/models/mining_session.dart';
import 'package:cubemine_pix/models/withdrawal.dart';
import 'package:cubemine_pix/services/ads_api.dart';
import 'package:cubemine_pix/services/auth_api.dart';
import 'package:cubemine_pix/services/cubes_api.dart';
import 'package:cubemine_pix/services/mining_api.dart';
import 'package:cubemine_pix/services/pix_api.dart';
import 'package:cubemine_pix/services/rewarded_ad_service.dart';
import 'package:cubemine_pix/services/wallet_api.dart';

AppUser fakeAppUser({String email = 'user@example.com', String? pixKey}) => AppUser(
      id: 1,
      email: email,
      phone: null,
      pixKey: pixKey,
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
  String? pixKeyToReturn;
  Object? throwOnLogin;
  Object? throwOnRegister;

  @override
  Future<AppUser> login() async {
    loginCalled = true;
    if (throwOnLogin != null) throw throwOnLogin!;
    return fakeAppUser(pixKey: pixKeyToReturn);
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
  Object? throwOnConfirm;
  int confirmCallCount = 0;
  int? lastConfirmedAdViewId;
  int? lastConfirmedUserId;

  @override
  Future<AdView> watch({required String adNetwork}) async {
    if (throwOnWatch != null) throw throwOnWatch!;
    return AdView(id: nextAdViewId, status: 'pending');
  }

  @override
  Future<AdView> confirm({required int adViewId, required int userId}) async {
    confirmCallCount++;
    lastConfirmedAdViewId = adViewId;
    lastConfirmedUserId = userId;
    if (throwOnConfirm != null) throw throwOnConfirm!;
    return AdView(id: adViewId, status: 'confirmed');
  }
}

/// Fake do RewardedAd real (google_mobile_ads) -- [earnedReward] controla
/// se o "anúncio" foi assistido até o fim (default true, o caminho feliz);
/// setar false simula o usuário fechando/pulando antes do fim.
class FakeRewardedAdService implements RewardedAdService {
  bool earnedReward = true;
  int loadAndShowCallCount = 0;

  @override
  Future<bool> loadAndShow() async {
    loadAndShowCallCount++;
    return earnedReward;
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

  /// Sessão RUNNING já existente para o cubo, simulando GET
  /// /mining/active-session -- null (default) simula "nenhuma sessão
  /// ativa", igual a um cubo idle de verdade.
  int activeSessionCallCount = 0;
  MiningSession? activeSessionToReturn;
  Object? throwOnActiveSession;

  @override
  Future<MiningSession?> activeSession({required int cubeId}) async {
    activeSessionCallCount++;
    if (throwOnActiveSession != null) throw throwOnActiveSession!;
    return activeSessionToReturn;
  }

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

  int epicBonusCallCount = 0;
  int epicBonusFailuresBeforeSuccess = 0;
  Object? throwOnEpicBonus;
  MiningSession? epicBonusResult;
  int? lastEpicBonusSessionId;
  int? lastEpicBonusAdViewId;

  @override
  Future<MiningSession> applyEpicBonus({required int sessionId, required int adViewId}) async {
    epicBonusCallCount++;
    lastEpicBonusSessionId = sessionId;
    lastEpicBonusAdViewId = adViewId;
    if (throwOnEpicBonus != null) throw throwOnEpicBonus!;
    if (epicBonusCallCount <= epicBonusFailuresBeforeSuccess) {
      throw const ApiException(statusCode: 400, message: 'ad_view is not confirmed');
    }
    return epicBonusResult ?? sessionToReturn!;
  }

  int speedupCallCount = 0;
  int speedupFailuresBeforeSuccess = 0;
  Object? throwOnSpeedup;
  MiningSession? speedupResult;
  int? lastSpeedupSessionId;
  int? lastSpeedupAdViewId;

  @override
  Future<MiningSession> applySpeedup({required int sessionId, required int adViewId}) async {
    speedupCallCount++;
    lastSpeedupSessionId = sessionId;
    lastSpeedupAdViewId = adViewId;
    if (throwOnSpeedup != null) throw throwOnSpeedup!;
    if (speedupCallCount <= speedupFailuresBeforeSuccess) {
      throw const ApiException(statusCode: 400, message: 'ad_view is not confirmed');
    }
    return speedupResult ?? sessionToReturn!;
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

/// Fake controlável de PixApi: [withdrawResultsQueue] permite simular o
/// mesmo saque mudando de status entre chamadas sucessivas de
/// listWithdrawals (ex: "processing" na primeira consulta, "paid" na
/// segunda), simulando o backend confirmando o pagamento entre um tick de
/// polling e outro do WithdrawController.
class FakePixApi implements PixApi {
  int withdrawCallCount = 0;
  Withdrawal? withdrawResult;
  Object? throwOnWithdraw;
  String? lastIdempotencyKey;
  double? lastAmount;
  String? lastPixKey;

  int listWithdrawalsCallCount = 0;
  List<List<Withdrawal>> listWithdrawalsQueue = [];
  Object? throwOnListWithdrawals;

  @override
  Future<Withdrawal> withdraw({
    required double amount,
    String? pixKey,
    required String idempotencyKey,
  }) async {
    withdrawCallCount++;
    lastAmount = amount;
    lastPixKey = pixKey;
    lastIdempotencyKey = idempotencyKey;
    if (throwOnWithdraw != null) throw throwOnWithdraw!;
    return withdrawResult!;
  }

  @override
  Future<List<Withdrawal>> listWithdrawals() async {
    listWithdrawalsCallCount++;
    if (throwOnListWithdrawals != null) throw throwOnListWithdrawals!;
    if (listWithdrawalsQueue.isEmpty) return const [];
    final index = (listWithdrawalsCallCount - 1).clamp(0, listWithdrawalsQueue.length - 1);
    return listWithdrawalsQueue[index];
  }
}

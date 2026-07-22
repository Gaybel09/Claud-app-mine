import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  try {
    await Firebase.initializeApp();
  } catch (error) {
    // Fase 1 ainda não tem um projeto Firebase real conectado. Rode
    // `flutterfire configure` (ou adicione google-services.json /
    // GoogleService-Info.plist) antes de builds que dependam de auth de
    // verdade -- sem isso, login/cadastro vão falhar em runtime, mas o
    // resto do app shell ainda renderiza para desenvolvimento de UI.
    debugPrint('Firebase not configured yet: $error');
  }

  runApp(const CubeMinePixApp());
}

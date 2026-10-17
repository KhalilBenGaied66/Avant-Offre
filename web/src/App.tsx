import ShortlistPage from "./components/ShortlistPage";
import TenderPage from "./components/TenderPage";
import { useRoute } from "./router";

export default function App() {
  const route = useRoute();
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          Avant-Offre
        </a>
        <span className="tagline">Préparation des décisions go / no-go — données publiques DECP et BOAMP</span>
      </header>
      <main>
        {route.page === "tender" && route.id ? (
          <TenderPage id={route.id} siret={route.params.get("siret") ?? ""} />
        ) : (
          <ShortlistPage siret={route.params.get("siret") ?? ""} week={route.params.get("week") ?? ""} />
        )}
      </main>
      <footer className="footer">
        Outil d'aide à la décision : la décision appartient au comité. Aucun envoi vers les acheteurs ou les plateformes.
      </footer>
    </div>
  );
}

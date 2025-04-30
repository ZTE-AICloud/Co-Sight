import {NgModule} from "@angular/core";
import {RouterModule, Routes} from "@angular/router";
import {LoginGuard, UnLoggedInGuard} from "./can-activate-guard";
import {UnLoggedIn} from "./pages/unlogged-in/login";
import {UnLoggedInModule} from "./pages/unlogged-in/login.module";
import {ManusChatbot} from './pages/manus-chatbot/manus-chatbot';
import {ManusChatbotModule} from './pages/manus-chatbot/manus-chatbot.module';

const routes: Routes = [
    {
        path: '',
        component: ManusChatbot,
        canActivate: [UnLoggedInGuard],
    },
    {
        path: 'manus',
        component: ManusChatbot,
        canActivate: [UnLoggedInGuard],
    },
    {
        path: 'login',
        component: UnLoggedIn,
        canActivate: [LoginGuard],
    },
    {
        path: '**',
        component: ManusChatbot,
        canActivate: [UnLoggedInGuard],
    }
]

@NgModule({
    imports: [
        RouterModule.forRoot(routes), UnLoggedInModule, ManusChatbotModule
    ],
    exports: [RouterModule]
})
export class UIDRouterModule {
}

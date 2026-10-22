/* Explicit finite capital gift in deity mode, never ordinary construction. */
class ScenarioCapitalFunding {
    require_fixed_fleet=false; policy_version=1; policy_company=0; autorenew_set=false;
    attempted=false; completed=false; resumed=false;
    balance_before=-1; balance_after=-1; loan_before=-1; loan_after=-1; delta=0;
    income_before=-1;income_after=-1;expenses_before=-1;expenses_after=-1;
    function Save() {
        local data={schema=1,attempted=attempted,completed=completed,balance_before=balance_before,
            balance_after=balance_after,loan_before=loan_before,loan_after=loan_after,delta=delta,income_before=income_before,income_after=income_after,expenses_before=expenses_before,expenses_after=expenses_after};
        if(require_fixed_fleet){data.schema=2;data.policy_version<-policy_version;data.policy_company<-policy_company;
            data.autorenew_set<-autorenew_set;data.autorenew_enabled<-GSCompany.GetAutoRenewStatus(policy_company);}
        return data;
    }
    function Load(data) {
        resumed=true;
        if(typeof data!="table"||!("schema" in data)||(data.schema!=1&&data.schema!=2))throw "CAPITAL_SAVE_INVALID";
        foreach(k in ["attempted","completed","balance_before","balance_after","loan_before","loan_after","delta","income_before","income_after","expenses_before","expenses_after"])
            if(!(k in data))throw "CAPITAL_SAVE_INVALID";
        if(require_fixed_fleet) {
            if(data.schema!=2||!("policy_version" in data)||data.policy_version!=1||
                !("policy_company" in data)||data.policy_company!=0||
                !("autorenew_set" in data)||typeof data.autorenew_set!="bool"||
                !("autorenew_enabled" in data)||typeof data.autorenew_enabled!="bool"||
                (data.completed&&(!data.autorenew_set||data.autorenew_enabled))||
                GSCompany.ResolveCompanyID(0)!=0||
                GSCompany.GetAutoRenewStatus(0)!=data.autorenew_enabled)throw "COMPANY_POLICY_SAVE_MISMATCH";
            autorenew_set=data.autorenew_set;
        }
        attempted=data.attempted;completed=data.completed;balance_before=data.balance_before;
        balance_after=data.balance_after;loan_before=data.loan_before;loan_after=data.loan_after;delta=data.delta;
        income_before=data.income_before;income_after=data.income_after;expenses_before=data.expenses_before;expenses_after=data.expenses_after;
    }
    function InitializeCompanyPolicy(company) {
        if(!require_fixed_fleet)return true;
        local mode=GSCompanyMode(company);
        if(!GSCompanyMode.IsValid()||GSCompany.ResolveCompanyID(company)!=company)return false;
        autorenew_set=GSCompany.SetAutoRenewStatus(false);
        local disabled=!GSCompany.GetAutoRenewStatus(company);mode=null;
        return autorenew_set&&disabled;
    }
    function Loan(company) {
        local mode=GSCompanyMode(company);
        if(!GSCompanyMode.IsValid())throw "CAPITAL_COMPANY_MODE_INVALID";
        local loan=GSCompany.GetLoanAmount();mode=null;return loan;
    }
    function Handle(q, preplanning) {
        if(typeof q!="table"||!("type" in q)||q.type!="scenario_capital")return false;
        if(q.len()!=7||!("protocol" in q)||typeof q.protocol!="integer"||q.protocol!=1||!("request_id" in q)||
            typeof q.request_id!="string"||q.request_id.len()<1||q.request_id.len()>64||
            !("op" in q)||typeof q.op!="string"||!("company" in q)||typeof q.company!="integer"||q.company!=0||
            !("target" in q)||typeof q.target!="integer"||q.target!=500000||
            !("preset" in q)||typeof q.preset!="string"||q.preset!="high-budget-500k"||(q.op!="initialize"&&q.op!="read"))
            throw "CAPITAL_REQUEST_INVALID";
        local valid=GSCompany.ResolveCompanyID(q.company)==q.company;
        local setting_valid=GSGameSettings.IsValid("difficulty.infinite_money");
        local infinite=setting_valid&&GSGameSettings.GetValue("difficulty.infinite_money")!=0;
        if(valid&&GSCompany.GetBankBalance(q.company)==2147483647)infinite=true;
        local status="READ";
        if(!GSCompanyMode.IsDeity())status="INVALID_DEITY";
        else if(GSCompany.ResolveCompanyID(q.company)!=q.company)status="INVALID_COMPANY";
        else if(!setting_valid)status="INFINITE_MONEY_SETTING_UNAVAILABLE";
        else if(infinite)status="INFINITE_MONEY_FORBIDDEN";
        else if(q.op=="initialize") {
            if(resumed)status="RESUMED_FUNDING_FORBIDDEN";
            else if(attempted)status="FUNDING_ALREADY_ATTEMPTED";
            else if(!preplanning||GSVehicleList().Count()!=0)status="FUNDING_AFTER_PLANNING_FORBIDDEN";
            else {
                attempted=true;balance_before=GSCompany.GetBankBalance(q.company);loan_before=Loan(q.company);
                income_before=GSCompany.GetQuarterlyIncome(q.company,GSCompany.CURRENT_QUARTER);
                expenses_before=GSCompany.GetQuarterlyExpenses(q.company,GSCompany.CURRENT_QUARTER);
                local policy_ok=InitializeCompanyPolicy(q.company);
                delta=q.target-balance_before;
                local result=policy_ok&&(delta==0||GSCompany.ChangeBankBalance(q.company,delta,GSCompany.EXPENSES_OTHER,GSMap.TILE_INVALID));
                balance_after=GSCompany.GetBankBalance(q.company);loan_after=Loan(q.company);
                income_after=GSCompany.GetQuarterlyIncome(q.company,GSCompany.CURRENT_QUARTER);
                expenses_after=GSCompany.GetQuarterlyExpenses(q.company,GSCompany.CURRENT_QUARTER);
                completed=result&&balance_after==q.target&&loan_after==loan_before&&income_after==income_before&&expenses_after==expenses_before;
                status=!policy_ok?"COMPANY_POLICY_INITIALIZATION_FAILED":completed?"FUNDED":"FUNDING_READBACK_FAILED";
            }
        } else {
            balance_after=GSCompany.GetBankBalance(q.company);loan_after=Loan(q.company);
            income_after=GSCompany.GetQuarterlyIncome(q.company,GSCompany.CURRENT_QUARTER);
            expenses_after=GSCompany.GetQuarterlyExpenses(q.company,GSCompany.CURRENT_QUARTER);
        }
        local r={type="scenario_capital",protocol=1,request_id=q.request_id,preset=q.preset,status=status,
            company=q.company,target=q.target,balance_before=balance_before,balance_after=balance_after,
            loan_before=loan_before,loan_after=loan_after,delta=delta,infinite_money=infinite,
            attempted=attempted,completed=completed,resumed=resumed,income_before=income_before,income_after=income_after,expenses_before=expenses_before,expenses_after=expenses_after,vehicles=GSVehicleList().Count()};
        if(require_fixed_fleet){r.policy_version<-policy_version;r.policy_company<-policy_company;
            r.autorenew_set<-autorenew_set;r.autorenew_enabled<-valid?GSCompany.GetAutoRenewStatus(q.company):true;
            if(status=="READ"&&(!autorenew_set||r.autorenew_enabled))r.status="COMPANY_POLICY_READBACK_FAILED";}
        if(!GSAdmin.Send(r))throw "CAPITAL_RESPONSE_SEND_FAILED";
        GSLog.Info("CAPITAL_RESPONSE "+q.request_id+" "+status);return true;
    }
}

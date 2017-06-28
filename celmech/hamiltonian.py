from sympy import S, diff, lambdify, symbols, sqrt, cos, numbered_symbols, simplify
from scipy.integrate import ode
import numpy as np
import rebound
from celmech.transformations import jacobi_masses_from_sim, poincare_vars_from_sim
from celmech.disturbing_function import laplace_coefficient

class Hamiltonian(object):
    def __init__(self, H, pqpairs, initial_conditions, params, Nparams):
        self.pqpairs = pqpairs
        self.params = params
        self.Nparams = Nparams
        self.initial_conditions = initial_conditions
        self.H = H
        self._update()

    def integrate(self, time):
        if time > self.integrator.t:
            try:
                self.integrator.integrate(time)
            except:
                raise AttributeError("Need to initialize Hamiltonian")

    def _update(self):
        self.derivs = {}
        for pqpair in self.pqpairs:
            p,q = pqpair
            self.derivs[p] = -diff(self.H, q)
            self.derivs[q] = diff(self.H, p)
        
        self.NH = self.H
        for i, param in enumerate(self.params):
            try:
                self.NH = self.NH.subs(param, self.Nparams[i])
            except KeyError:
                raise AttributeError("need to pass keyword {0} to hamiltonian.integrate".format(param))
        symvars = [item for pqpair in self.pqpairs for item in pqpair]
        self.Nderivs = []
        for pqpair in self.pqpairs:
            p,q = pqpair
            self.Nderivs.append(lambdify(symvars, -diff(self.NH, q), 'numpy'))
            self.Nderivs.append(lambdify(symvars, diff(self.NH, p), 'numpy'))
        
        def diffeq(t, y):
            dydt = [deriv(*y) for deriv in self.Nderivs]
            #print(t, y, dydt)
            return dydt
        self.integrator = ode(diffeq).set_integrator('lsoda',nsteps=1e4)
        self.integrator.set_initial_value(self.initial_conditions, 0)

class newAndoyerHamiltonian(Hamiltonian):
    def __init__(self, k, NA, NB, NC, Phi0, phi0):
        Phi, phi, A, B, C = symbols('Phi, phi, A, B, C')
        self.pqpairs = [(Phi, phi)]
        self.params = [A, B, C]
        self.Nparams = [NA, NB, NC]
        self.initial_conditions = [Phi0, phi0]
        self.H = S(1)/2*A*Phi**2 + B*Phi + C*Phi**(k/S(2))*cos(phi)
        self._update()

class AndoyerHamiltonian(Hamiltonian):
    def __init__(self, k, NPhiprime, Phi0, phi0):
        Phi, phi, Phiprime = symbols('Phi, phi, Phiprime')
        self.pqpairs = [(Phi, phi)]
        self.params = [Phiprime]
        self.Nparams = [NPhiprime]
        self.initial_conditions = [Phi0, phi0]
        self.H = S(1)/2*(Phi-Phiprime)**2 + Phi**(k/S(2))*cos(phi)
        self._update()
    @classmethod
    def from_Simulation(cls, sim, j, k):

        return cls(k, NPhiprime, Phi0, phi0)
        
class CartesianAndoyerHamiltonian(Hamiltonian):
    def __init__(self, k, NPhiprime, Phi0, phi0):
        X,Y,Phiprime = symbols('X, Y, Phiprime')
        self.pqpairs = [(X, Y)]
        self.params = [Phiprime]
        self.Nparams = [NPhiprime]
        self.initial_conditions = [np.sqrt(2.*Phi0)*np.cos(phi0), np.sqrt(2.*Phi0)*np.sin(phi0)]
        self.H = S(1)/2*((X**2 + Y**2)/S(2)-Phiprime)**2 + S(1)/sqrt(S(2))*X*((X**2+Y**2)/2)**((k-1)/S(2))
        self._update()

class HamiltonianThetas(Hamiltonian):
    def __init__(self, sim, j, k):
        self.pham = HamiltonianPoincare()
        self.pham.initialize_from_sim(sim)
        self.pham.add_all_resonance_subterms(self, 1, 2, j, k)
        print(self.pham.H)

class HamiltonianCombineEccentricityTransform(Hamiltonian):
    def __init__(self):
        self.resonance_indices = []
        self.integrator = None
        self.N = 0
    def initialize_from_sim(self,sim):
        # add sympy symbols
        #
        #  parameters
        self.m = list(symbols("m0:{0}".format(sim.N)))
        self.M = list(symbols("M0:{0}".format(sim.N)))
        self.mu = list(symbols("mu0:{0}".format(sim.N)))
        #  canonical variables
        self.Psi = list(symbols("Psi0:{0}".format(sim.N)))
        self.psi = list(symbols("psi0:{0}".format(sim.N)))
        self.Phi = list(symbols("Phi0:{0}".format(sim.N)))
        self.phi = list(symbols("phi0:{0}".format(sim.N)))
    def initialize_from_PoincareHamiltonian(self,PHam):
        # add sympy symbols
        #
        #  parameters
        self.m = PHam.m
        self.M = PHam.M
        self.mu = PHam.mu
        self.N = PHam.N
        #  canonical variables
        self.Psi = list(symbols("Psi0:{0}".format(self.N)))
        self.psi = list(symbols("psi0:{0}".format(self.N)))
        self.Phi = list(symbols("Phi0:{0}".format(self.N)))
        self.phi = list(symbols("phi0:{0}".format(self.N)))
        
        self.H = S(0)
        self.params = PHam.params
        self.pqpairs = []
        for i in range(1,PHam.N):
            self.pqpairs.append((self.Psi[i],self.psi[i]))
            self.pqpairs.append((self.Phi[i], self.phi[i]))
            self.add_Hkep_term(i)
    
        self.a = PHam.a # add dummy for star to match indices
        self.Nm, self.NM, self.Nmu = PHam.Nm, PHam.NM, PHam.Nmu
        self.Nparams = self.Nmu + self.Nm + self.NM
        self.initial_conditions = PHam.initial_conditions
        self._update()

    def add_Hkep_term(self,index):
        m, M, mu, Lambda = self._get_HKep_symbols(index)
        self.H +=  -mu / (2 * Lambda**2)
    def _get_HKep_symbols(self, index):
        if index==1:
            Lambda = self.Phi[index]-self.Psi[index]
        else:
            Lambda = self.Phi[index] - self.Psi[index] + self.Psi[index-1]
        return self.m[index], self.M[index], self.mu[index], Lambda 

    def add_all_resonance_subterms(self, indexIn, indexOut, j, k):
        """
        Add all the terms associated the j:j-k MMR between planets 'indexIn' and 'indexOut'.
        Inputs:
        indexIn     -    index of the inner planet
        indexOut    -    index of the outer planet
        j           -    together with k specifies the MMR j:j-k
        k           -    order of the resonance
        """
        for l in range(k+1):
            self.add_single_resonance(indexIn,indexOut, j, k, l)

    def add_single_resonance(self, indexIn, indexOut, j, k, l):
        """
        Add a single term associated the j:j-k MMR between planets 'indexIn' and 'indexOut'.
        Inputs:
        indexIn     -   index of the inner planet
        indexOut    -   index of the outer planet
        j           -   together with k specifies the MMR j:j-k
        k           -   order of the resonance
        l           -   picks out the eIn^(l) * eOut^(k-l) subterm
        """
        # Canonical variables
        assert indexOut == indexIn + 1,"Only resonances for adjacent pairs are currently supported"
        mIn, MIn, muIn, mOut, MOut, muOut, LambdaIn, LambdaOut, psi, PhiIn, phiIn, PhiOut, phiOut = self._get_pair_symbols(indexIn,indexOut)
        
        # Resonance index
        assert l<=k, "Invalid resonance term, l must be less than or equal to k."
        alpha = self.a[indexIn]/self.a[indexOut]

        # Resonance components
        from celmech.disturbing_function import general_order_coefficient
        #
        Cjkl = symbols( "C_{0}\,{1}\,{2}".format(j,k,l) )
        self.params.append(Cjkl)
        self.Nparams.append(general_order_coefficient(j,k,l,alpha))
        #
        eccIn = sqrt(2*PhiIn/LambdaIn)
        eccOut = sqrt(2*PhiOut/LambdaOut)
        #
        costerm = cos( (j-k+l) * psi + l * phiIn + (k-l) * phiOut )
        #
        prefactor = -muOut *( mIn / MIn) / (LambdaOut**2)
        # Keep track of resonances
        self.resonance_indices.append((indexIn,indexOut,(j,k,l)))
        # Update Hamiltonian
        self.H += prefactor * Cjkl * (eccIn**l) * (eccOut**(k-l)) * costerm
        self._update()
    def _get_pair_symbols(self,indexIn,indexOut):
        mIn, MIn, muIn, LambdaIn = self._get_HKep_symbols(indexIn)
        mOut, MOut, muOut, LambdaOut = self._get_HKep_symbols(indexOut)
        psi = self.psi[indexIn]
        PhiIn, PhiOut = self.Phi[indexIn],self.Phi[indexOut]
        phiIn, phiOut = self.phi[indexIn],self.phi[indexOut]
        return mIn, MIn, muIn, mOut, MOut, muOut, LambdaIn, LambdaOut, psi, PhiIn, phiIn, PhiOut, phiOut

class HamiltonianPoincare(Hamiltonian):
    def __init__(self):
        self.resonance_indices = []
        self.integrator = None

    def initialize_from_sim(self, sim):
        # add sympy symbols
        self.m = list(symbols("m0:{0}".format(sim.N)))
        self.M = list(symbols("M0:{0}".format(sim.N)))
        self.mu = list(symbols("mu0:{0}".format(sim.N)))
        self.Lambda = list(symbols("Lambda0:{0}".format(sim.N)))
        self.lam = list(symbols("lambda0:{0}".format(sim.N)))
        self.Gamma = list(symbols("Gamma0:{0}".format(sim.N)))
        self.gamma = list(symbols("gamma0:{0}".format(sim.N)))
        
        # add symbols needed by base Hamiltonian class
        self.N = sim.N
        self.H = S(0)
        self.params = self.mu + self.m + self.M
        self.pqpairs = []
        for i in range(1,sim.N):
            self.pqpairs.append((self.Lambda[i],self.lam[i]))
            self.pqpairs.append((self.Gamma[i], self.gamma[i]))
            self.add_Hkep_term(i)
        
        # add numerical values
        self.a = [0]+[sim.particles[i].a for i in range(1,sim.N)] # add dummy for star to match indices
        self.Nm, self.NM, self.Nmu = jacobi_masses_from_sim(sim)
        self.Nparams = self.Nmu + self.Nm + self.NM
        self.initial_conditions = poincare_vars_from_sim(sim, average_synodic_terms=True)
        
        # calculate Hamilton's equations symbolically and substitute numerical values
        self._update()

    def add_Hkep_term(self, index):
        """
        Add the Keplerian component of the Hamiltonian for planet ''.
        """
        m, M, mu, Lambda, lam, Gamma, gamma = self._get_symbols(index)
        self.H +=  -mu / (2 * Lambda**2)

    def add_single_resonance(self, indexIn, indexOut, j, k, l):
        """
        Add a single term associated the j:j-k MMR between planets 'indexIn' and 'indexOut'.
        Inputs:
        indexIn     -   index of the inner planet
        indexOut    -   index of the outer planet
        j           -   together with k specifies the MMR j:j-k
        k           -   order of the resonance
        l           -   picks out the eIn^(l) * eOut^(k-l) subterm
        """
        # Canonical variables
        mIn, MIn, muIn, LambdaIn, lambdaIn, GammaIn, gammaIn = self._get_symbols(indexIn)
        mOut, MOut, muOut, LambdaOut, lambdaOut, GammaOut, gammaOut = self._get_symbols(indexOut)
        
        # Resonance index
        assert l<=k, "Invalid resonance term, l must be less than or equal to k."
        alpha = self.a[indexIn]/self.a[indexOut]

        # Resonance components
        from celmech.disturbing_function import general_order_coefficient
        #
        Cjkl = symbols( "C_{0}\,{1}\,{2}".format(j,k,l) )
        self.params.append(Cjkl)
        self.Nparams.append(general_order_coefficient(j,k,l,alpha))
        #
        eccIn = sqrt(2*GammaIn/LambdaIn)
        eccOut = sqrt(2*GammaOut/LambdaOut)
        #
        costerm = cos( j * lambdaOut - (j-k) * lambdaIn + l * gammaIn + (k-l) * gammaOut )
        #
        prefactor = -muOut *( mIn / MIn) / (LambdaOut**2)
    
        # Keep track of resonances
        self.resonance_indices.append((indexIn,indexOut,(j,k,l)))
        # Update Hamiltonian
        self.H += prefactor * Cjkl * (eccIn**l) * (eccOut**(k-l)) * costerm
        self._update()
    
    def add_all_resonance_subterms(self, indexIn, indexOut, j, k):
        """
        Add all the terms associated the j:j-k MMR between planets 'indexIn' and 'indexOut'.
        Inputs:
        indexIn     -    index of the inner planet
        indexOut    -    index of the outer planet
        j           -    together with k specifies the MMR j:j-k
        k           -    order of the resonance
        """
        for l in range(k+1):
            self.add_single_resonance(indexIn,indexOut, j, k, l)

    def _get_symbols(self, index):
        return self.m[index], self.M[index], self.mu[index], self.Lambda[index], self.lam[index], self.Gamma[index], self.gamma[index]
    
    @property
    def NLambda(self):
        return self.integrator.y[::4]
    @property
    def Nlambda(self):
        return np.mod(self.integrator.y[1::4],2*np.pi)
    @property
    def NGamma(self):
        return self.integrator.y[2::4]
    @property
    def Ngamma(self):
        return np.mod(self.integrator.y[3::4],2*np.pi)

